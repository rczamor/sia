from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.config import router as config_router
from app.api.context import router as context_router
from app.api.ingest import router as ingest_router
from app.api.knowledge import router as knowledge_router
from app.auth import router as auth_router
from app.context.store.layout import scaffold_store
from app.database import engine
from app.gateway.api import router as gateway_router
from app.config import settings
from app.gateway.authn import AuthMiddleware, SecurityHeadersMiddleware
from app.gateway.mcp import build_mcp_asgi_app, mcp_server
from app.jobs.queue import job_queue
from app.runtime import get_runtime, shutdown_runtime
from app.ui import router as ui_router


INSECURE_JWT_SECRETS = {"", "change-me", "change-this-to-a-random-secret"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to boot with a default/blank JWT secret: anyone could forge an owner
    # session token. Set JWT_SECRET (openssl rand -hex 32).
    if settings.jwt_secret in INSECURE_JWT_SECRETS:
        raise RuntimeError(
            "JWT_SECRET is unset or default. Set a strong JWT_SECRET before starting "
            "(openssl rand -hex 32) — a default secret lets anyone forge an owner token."
        )
    runtime = await get_runtime()  # discover + initialize enabled plugins
    await scaffold_store(runtime.context_store)  # idempotent store layout
    async with job_queue.open_async():  # web process defers jobs; workers run them
        async with mcp_server.session_manager.run():  # streamable HTTP sessions
            yield
    await shutdown_runtime()
    await engine.dispose()


app = FastAPI(title="Sia — Context Engine", version="0.1.0", lifespan=lifespan)

app.add_middleware(AuthMiddleware)  # deny-by-default: see app/gateway/authn.py
app.add_middleware(SecurityHeadersMiddleware)
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Sia-Key"],
    )

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# API routes
app.include_router(auth_router)
app.include_router(ingest_router)
app.include_router(knowledge_router)
app.include_router(context_router)
app.include_router(config_router)

app.include_router(gateway_router)

# Admin UI routes
app.include_router(ui_router)

# MCP connector (own key auth inside the mount)
app.mount("/mcp", build_mcp_asgi_app())


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "sia"}

"""Deny-by-default authentication middleware + a small in-memory rate limiter.

Every route requires an authenticated principal unless its path is explicitly
public. Three credentials resolve to a principal:
- owner session JWT (HttpOnly cookie ``sia_session`` — the admin UI), or
- owner JWT as ``Authorization: Bearer <jwt>`` (programmatic admin), or
- API key as ``Authorization: Bearer sia_<key>`` / ``X-Sia-Key`` (agents).

Unauthenticated requests to /api/context/build run as the rate-limited visitor
principal (public-only, no fallback). /mcp enforces its own key auth in the mount.

The rate limiter is in-memory per process — correct for the single-instance
deployments this targets; swap for a shared store before scaling out.
"""

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from app.auth import verify_token_optional
from app.config import settings
from app.context.principals import PrincipalService

SESSION_COOKIE = "sia_session"

PUBLIC_PREFIXES = (
    "/api/health",
    "/login",
    "/logout",
    "/api/auth/login",
    "/static/",
    "/mcp",  # enforces its own key auth
    "/api/ingest/slack",  # enforces its own webhook token
)
VISITOR_PREFIXES = ("/api/context/build",)
OWNER_PREFIXES = (
    "/admin",
    "/api/config",
    "/api/context/review",
    "/api/context/consolidate",
    "/api/principals",
    "/docs",
    "/openapi.json",
    "/redoc",
)


class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True


visitor_limiter = SlidingWindowLimiter(max_requests=30, window_seconds=60)
login_limiter = SlidingWindowLimiter(max_requests=10, window_seconds=60)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path.startswith(PUBLIC_PREFIXES) or path == "/":
            if path.startswith(("/login", "/api/auth/login")) and request.method == "POST":
                if not login_limiter.allow(_client_ip(request)):
                    return JSONResponse({"detail": "Too many attempts"}, status_code=429)
            return await call_next(request)

        principal = await _resolve_principal(request)

        if principal is None and path.startswith(VISITOR_PREFIXES):
            if not visitor_limiter.allow(_client_ip(request)):
                return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
            from app.database import async_session

            async with async_session() as db:
                principal = await PrincipalService(db).visitor()

        if principal is None:
            if path.startswith("/admin"):
                return RedirectResponse("/login", status_code=303)
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        if path.startswith(OWNER_PREFIXES) and not principal.is_owner:
            return JSONResponse({"detail": "Owner access required"}, status_code=403)

        request.state.principal = principal
        return await call_next(request)


async def _resolve_principal(request: Request):
    # 1. Owner session cookie / bearer JWT
    token = request.cookies.get(SESSION_COOKIE, "")
    authorization = request.headers.get("authorization", "")
    bearer = authorization.removeprefix("Bearer ").strip()
    api_key = request.headers.get("x-sia-key", "") or (
        bearer if bearer.startswith("sia_") else ""
    )

    from app.database import async_session

    if token or (bearer and not bearer.startswith("sia_")):
        email = verify_token_optional(token or bearer)
        if email == settings.admin_email:
            async with async_session() as db:
                return await PrincipalService(db).get("owner")
        return None

    # 2. API key
    if api_key:
        async with async_session() as db:
            principal = await PrincipalService(db).authenticate(api_key)
            await db.commit()
        return principal

    return None


def _client_ip(request: Request) -> str:
    if request.client:
        return request.client.host
    return "unknown"

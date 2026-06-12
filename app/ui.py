from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tables import ExpertiseArtifacts, MyThoughts, SourceContent
from app.runtime import get_runtime

router = APIRouter(tags=["admin-ui"])
templates = Jinja2Templates(directory="templates")


@router.get("/admin", response_class=HTMLResponse)
@router.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    # KB stats
    sources_count = (await db.execute(select(func.count(SourceContent.id)))).scalar() or 0
    thoughts_count = (await db.execute(select(func.count(MyThoughts.id)))).scalar() or 0
    artifacts_count = (await db.execute(select(func.count(ExpertiseArtifacts.id)))).scalar() or 0

    # Recent ingestions (last 10)
    recent = await db.execute(
        select(SourceContent).order_by(SourceContent.created_at.desc()).limit(10)
    )
    recent_items = recent.scalars().all()

    return templates.TemplateResponse(request, "dashboard.html", {
        "stats": {
            "sources": sources_count,
            "thoughts": thoughts_count,
            "artifacts": artifacts_count,
            "total": sources_count + thoughts_count + artifacts_count,
        },
        "recent_items": recent_items,
    })


@router.get("/admin/knowledge", response_class=HTMLResponse)
async def knowledge_browser(
    request: Request,
    q: str = "",
    pillar: str = "",
    db: AsyncSession = Depends(get_db),
):
    results = []
    if q:
        runtime = await get_runtime()
        search_service = runtime.search_service(db)
        pillar_filter = [pillar] if pillar else None
        results = await search_service.search(query=q, pillar=pillar_filter, limit=20)

    return templates.TemplateResponse(request, "knowledge.html", {
        "query": q,
        "pillar": pillar,
        "results": results,
    })


@router.get("/admin/knowledge/search", response_class=HTMLResponse)
async def knowledge_search_partial(
    request: Request,
    q: str = "",
    pillar: str = "",
    db: AsyncSession = Depends(get_db),
):
    """HTMX partial — returns just the results list."""
    results = []
    if q and len(q) >= 2:
        runtime = await get_runtime()
        search_service = runtime.search_service(db)
        pillar_filter = [pillar] if pillar else None
        results = await search_service.search(query=q, pillar=pillar_filter, limit=20)

    return templates.TemplateResponse(request, "partials/search_results.html", {
        "results": results,
    })


@router.get("/admin/ingest", response_class=HTMLResponse)
async def ingest_page(request: Request):
    return templates.TemplateResponse(request, "ingest.html", {})


@router.get("/admin/review", response_class=HTMLResponse)
async def review_page(request: Request, db: AsyncSession = Depends(get_db)):
    runtime = await get_runtime()
    pending = await runtime.review_service(db).pending()
    return templates.TemplateResponse(request, "review.html", {"pending": pending})


@router.get("/admin/graph", response_class=HTMLResponse)
async def graph_page(request: Request):
    return templates.TemplateResponse(request, "graph.html", {})


@router.get("/admin/health", response_class=HTMLResponse)
async def health_page(request: Request, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select as sa_select

    from app.api.context import context_health
    from app.models.tables import ContextBuilds

    health = await context_health(db)
    recent = (
        (
            await db.execute(
                sa_select(ContextBuilds).order_by(ContextBuilds.created_at.desc()).limit(15)
            )
        )
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        request, "health.html", {"health": health, "recent_builds": recent}
    )


@router.get("/admin/inspector", response_class=HTMLResponse)
async def inspector_page(request: Request, db: AsyncSession = Depends(get_db)):
    from app.context.principals import PrincipalService

    principals = await PrincipalService(db).list_all()
    return templates.TemplateResponse(
        request, "inspector.html", {"principals": [p for p in principals if p["enabled"]]}
    )


@router.post("/admin/inspector/run", response_class=HTMLResponse)
async def inspector_run(
    request: Request,
    goal: str = Form(...),
    principal_id: str = Form("owner"),
    budget_tokens: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    from app.context.principals import PrincipalService

    principal = await PrincipalService(db).get(principal_id)
    if principal is None:
        return HTMLResponse("<p>Unknown principal</p>", status_code=400)
    runtime = await get_runtime()
    # Route through build_context so inspector builds are scored and traced like
    # API/MCP builds (builder.build alone audits but never scores).
    artifact = await runtime.build_context(
        db,
        goal=goal,
        principal=principal,
        budget_tokens=int(budget_tokens) if budget_tokens.strip() else None,
    )
    return templates.TemplateResponse(
        request,
        "partials/artifact.html",
        {"artifact": artifact, "markdown": artifact.to_markdown()},
    )

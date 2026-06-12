from fastapi import APIRouter, Depends, Request
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

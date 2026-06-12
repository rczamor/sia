from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.ingestion import IngestionService
from app.data.knowledge_store import KnowledgeStore
from app.data.url_safety import UnsafeURLError, assert_safe_url
from app.database import get_db
from app.jobs.tasks import ingest_url_task
from app.models.schemas import IngestArtifactRequest, IngestThoughtRequest, IngestURLRequest
from app.runtime import get_runtime

router = APIRouter(prefix="/api/ingest", tags=["ingestion"])


async def _get_ingestion_service(db: AsyncSession) -> IngestionService:
    runtime = await get_runtime()
    return runtime.ingestion_service(db)


@router.post("/url", status_code=202)
async def ingest_url(request: IngestURLRequest, db: AsyncSession = Depends(get_db)):
    """Queue URL ingestion (fetch + classify are slow). Fast checks run inline so the
    caller gets immediate feedback; the worker re-validates during the actual fetch."""
    url = str(request.url)
    try:
        assert_safe_url(url)
    except UnsafeURLError as exc:
        raise HTTPException(status_code=400, detail=f"URL refused: {exc}")

    runtime = await get_runtime()
    store = KnowledgeStore(db, runtime.embedder)
    if await store.url_exists(url):
        raise HTTPException(status_code=409, detail="URL already exists in knowledge base")

    job_id = await ingest_url_task.defer_async(
        url=url,
        notes=request.notes,
        pillar_override=(
            [p.value for p in request.pillar_override] if request.pillar_override else None
        ),
    )
    return JSONResponse(
        status_code=202, content={"status": "queued", "job_id": job_id, "url": url}
    )


@router.post("/thought")
async def ingest_thought(request: IngestThoughtRequest, db: AsyncSession = Depends(get_db)):
    svc = await _get_ingestion_service(db)
    return await svc.ingest_thought(
        content=request.content,
        pillar=[p.value for p in request.pillar] if request.pillar else None,
        thought_type=request.thought_type.value,
        related_source_ids=request.related_source_ids,
    )


@router.post("/expertise")
async def ingest_artifact(request: IngestArtifactRequest, db: AsyncSession = Depends(get_db)):
    svc = await _get_ingestion_service(db)
    return await svc.ingest_artifact(
        title=request.title,
        content=request.content,
        artifact_type=request.artifact_type.value,
        domain=request.domain,
        pillar=[p.value for p in request.pillar],
    )

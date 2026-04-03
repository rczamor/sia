from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.schemas import IngestArtifactRequest, IngestThoughtRequest, IngestURLRequest
from app.providers.embeddings.ollama import OllamaEmbedding
from app.providers.llm.anthropic import AnthropicProvider
from app.services.ingestion import IngestionService
from app.services.lineage import LineageService, TrackedLLMProvider

router = APIRouter(prefix="/api/ingest", tags=["ingestion"])


def _get_ingestion_service(db: AsyncSession) -> IngestionService:
    embedder = OllamaEmbedding()
    raw_llm = AnthropicProvider()
    lineage = LineageService(db)
    llm = TrackedLLMProvider(raw_llm, lineage)
    return IngestionService(db, llm, embedder)


@router.post("/url")
async def ingest_url(request: IngestURLRequest, db: AsyncSession = Depends(get_db)):
    svc = _get_ingestion_service(db)
    result = await svc.ingest_url(
        url=str(request.url),
        notes=request.notes,
        pillar_override=[p.value for p in request.pillar_override] if request.pillar_override else None,
    )
    if "error" in result:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/thought")
async def ingest_thought(request: IngestThoughtRequest, db: AsyncSession = Depends(get_db)):
    svc = _get_ingestion_service(db)
    result = await svc.ingest_thought(
        content=request.content,
        pillar=[p.value for p in request.pillar] if request.pillar else None,
        thought_type=request.thought_type.value,
        related_source_ids=request.related_source_ids,
    )
    return result


@router.post("/expertise")
async def ingest_artifact(request: IngestArtifactRequest, db: AsyncSession = Depends(get_db)):
    svc = _get_ingestion_service(db)
    result = await svc.ingest_artifact(
        title=request.title,
        content=request.content,
        artifact_type=request.artifact_type.value,
        domain=request.domain,
        pillar=[p.value for p in request.pillar],
    )
    return result

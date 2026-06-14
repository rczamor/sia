import hmac
import re

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.data.ingestion import IngestionService
from app.data.knowledge_store import KnowledgeStore
from app.data.url_safety import UnsafeURLError, assert_safe_url
from app.database import get_db
from app.jobs.tasks import ingest_content_task, ingest_url_task
from app.models.schemas import IngestArtifactRequest, IngestThoughtRequest, IngestURLRequest
from app.runtime import get_runtime

router = APIRouter(prefix="/api/ingest", tags=["ingestion"])

URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>|]+")


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


class SlackIngestRequest(BaseModel):
    text: str


@router.post("/slack", status_code=202)
async def ingest_from_slack(
    request: SlackIngestRequest,
    db: AsyncSession = Depends(get_db),
    x_sia_slack_token: str = Header(default=""),
):
    """Slack capture channel: URLs in the message are queued as untrusted sources;
    remaining text is stored as an owner-tier thought."""
    if not settings.slack_webhook_secret:
        raise HTTPException(status_code=503, detail="Slack ingestion not configured")
    if not hmac.compare_digest(x_sia_slack_token, settings.slack_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    # Order matters for idempotency against Slack's webhook retries: do the
    # failure-prone thought (LLM classify) FIRST, deduped by recent identical
    # content, then enqueue URLs (idempotent at execution via url_exists). A
    # transient failure thus leaves nothing half-done, and a retry neither
    # duplicates the thought nor double-ingests a URL.
    remaining = URL_IN_TEXT_RE.sub("", request.text).strip()
    thought_id = None
    if remaining and len(remaining) > 10:
        thought_id = await _store_slack_thought_idempotent(db, remaining)

    urls = URL_IN_TEXT_RE.findall(request.text)
    queued = []
    for url in urls:
        url = url.rstrip(">.,)")
        try:
            assert_safe_url(url)
        except UnsafeURLError:
            continue
        queued.append(await ingest_url_task.defer_async(url=url))

    return {"status": "queued", "urls_queued": len(queued), "thought_id": thought_id}


async def _store_slack_thought_idempotent(db: AsyncSession, content: str) -> str:
    """Store a Slack-captured thought, reusing an identical thought created in the
    last 10 minutes so a webhook retry does not duplicate it."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models.tables import MyThoughts

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    existing = (
        await db.execute(
            select(MyThoughts.id)
            .where(MyThoughts.content == content, MyThoughts.created_at >= cutoff)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return str(existing)

    svc = await _get_ingestion_service(db)
    result = await svc.ingest_thought(content=content)
    return result["id"]


class WebhookIngestRequest(BaseModel):
    """One generic inbound payload. An automation platform (Zapier / n8n / Make)
    is the connector layer: it authenticates to the source, pulls the data, and
    maps it onto these fields — so Sia needs no per-source integration code."""

    title: str = Field(min_length=1, max_length=500)
    content: str = Field(default="", max_length=500_000)
    url: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=200)
    author: str | None = Field(default=None, max_length=200)


@router.post("/webhook", status_code=202)
async def ingest_from_webhook(
    request: WebhookIngestRequest,
    x_sia_webhook_token: str = Header(default=""),
):
    """Generic ingestion webhook for automation platforms. Authenticated by a
    shared secret (X-Sia-Webhook-Token); content lands at the untrusted tier and
    passes the review gate before it can be consolidated, exactly like other
    machine-fed intake.

    Provide `content` for sources the platform already fetched (auth-gated docs,
    Slack messages, form fields). If only a public `url` is given, it is queued
    for fetch+extract like /api/ingest/url instead."""
    if not settings.ingest_webhook_secret:
        raise HTTPException(status_code=503, detail="Ingestion webhook not configured")
    if not hmac.compare_digest(x_sia_webhook_token, settings.ingest_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    notes = f"via {request.source}" if request.source else None

    if request.content.strip():
        job_id = await ingest_content_task.defer_async(
            title=request.title,
            content=request.content,
            url=request.url,
            author=request.author,
            notes=notes,
        )
        return {"status": "queued", "job_id": job_id, "mode": "content"}

    if request.url:
        try:
            assert_safe_url(request.url)
        except UnsafeURLError as exc:
            raise HTTPException(status_code=400, detail=f"URL refused: {exc}")
        job_id = await ingest_url_task.defer_async(url=request.url, notes=notes)
        return {"status": "queued", "job_id": job_id, "mode": "url"}

    raise HTTPException(status_code=400, detail="Provide content or url")


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

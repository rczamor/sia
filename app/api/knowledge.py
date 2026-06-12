import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.schemas import SearchResponse, SearchResult
from app.data.knowledge_store import KnowledgeStore
from app.data.versioning import VersioningService
from app.runtime import get_runtime

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


async def _get_store(db: AsyncSession) -> KnowledgeStore:
    runtime = await get_runtime()
    return KnowledgeStore(db, runtime.embedder)


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str,
    pillar: list[str] | None = Query(default=None),
    tables: list[str] | None = Query(default=None),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
):
    runtime = await get_runtime()
    search_service = runtime.search_service(db)
    results = await search_service.search(
        query=q, tables=tables, pillar=pillar, date_from=date_from, date_to=date_to, limit=limit
    )
    return SearchResponse(
        results=[
            SearchResult(
                id=r["id"],
                entity_type=r["entity_type"],
                title=r.get("title"),
                content_preview=r.get("content_preview"),
                pillar=r.get("pillar", []),
                score=r["score"],
                created_at=r.get("created_at"),
            )
            for r in results
        ],
        total=len(results),
        query=q,
    )


@router.get("/sources")
async def list_sources(
    pillar: list[str] | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    store = await _get_store(db)
    items = await store.list_items("source_content", pillar=pillar, limit=limit, offset=offset)
    return [
        {
            "id": str(i.id), "title": i.title, "url": i.url, "summary": i.summary,
            "pillar": i.pillar, "source_type": i.source_type, "created_at": i.created_at,
        }
        for i in items
    ]


@router.get("/thoughts")
async def list_thoughts(
    pillar: list[str] | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    store = await _get_store(db)
    items = await store.list_items("my_thoughts", pillar=pillar, limit=limit, offset=offset)
    return [
        {
            "id": str(i.id), "content": i.content[:200], "pillar": i.pillar,
            "thought_type": i.thought_type, "maturity": i.maturity, "created_at": i.created_at,
        }
        for i in items
    ]


@router.get("/artifacts")
async def list_artifacts(
    pillar: list[str] | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    store = await _get_store(db)
    items = await store.list_items("expertise_artifacts", pillar=pillar, limit=limit, offset=offset)
    return [
        {
            "id": str(i.id), "title": i.title, "artifact_type": i.artifact_type,
            "pillar": i.pillar, "created_at": i.created_at,
        }
        for i in items
    ]


@router.get("/{table}/{item_id}")
async def get_item(table: str, item_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    store = await _get_store(db)
    item = await store.get_item(table, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    # Return full item as dict (exclude embedding)
    data = {c.name: getattr(item, c.name) for c in item.__table__.columns if c.name != "embedding"}
    data["id"] = str(data["id"])
    if "search_vector" in data:
        del data["search_vector"]
    return data


@router.put("/{table}/{item_id}")
async def update_item(
    table: str, item_id: uuid.UUID, updates: dict, db: AsyncSession = Depends(get_db)
):
    store = await _get_store(db)
    # Remove fields that shouldn't be directly updated
    updates.pop("id", None)
    updates.pop("embedding", None)
    updates.pop("search_vector", None)
    updates.pop("created_at", None)

    item = await store.update_item(table, item_id, updates)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Create version
    versioning = VersioningService(db)
    snapshot = {c.name: getattr(item, c.name) for c in item.__table__.columns
                if c.name not in ("embedding", "search_vector")}
    snapshot["id"] = str(snapshot["id"])
    await versioning.create_version(
        entity_type=table, entity_id=item_id,
        content_snapshot=snapshot, change_type="manual_edit",
    )
    await db.commit()

    return {"message": "Updated", "id": str(item_id)}


@router.delete("/{table}/{item_id}")
async def delete_item(table: str, item_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    store = await _get_store(db)
    deleted = await store.delete_item(table, item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")
    await db.commit()
    return {"message": "Deleted", "id": str(item_id)}


# --- Versions ---

@router.post("/{table}/{item_id}/restore/{version_number}")
async def restore_version(
    table: str, item_id: uuid.UUID, version_number: int, db: AsyncSession = Depends(get_db)
):
    """Restore an item to a previous version snapshot (a new version is recorded,
    so restores are themselves audited and reversible)."""
    versioning = VersioningService(db)
    version = await versioning.get_version(table, item_id, version_number)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    store = await _get_store(db)
    snapshot = {
        k: v
        for k, v in version.content_snapshot.items()
        if k not in ("id", "created_at", "updated_at", "embedding", "search_vector")
    }
    item = await store.update_item(table, item_id, snapshot)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    new_snapshot = {c.name: getattr(item, c.name) for c in item.__table__.columns
                    if c.name not in ("embedding", "search_vector")}
    new_snapshot["id"] = str(new_snapshot["id"])
    await versioning.create_version(
        entity_type=table, entity_id=item_id, content_snapshot=new_snapshot,
        change_type="update", change_reason=f"restore to v{version_number}",
    )
    await db.commit()
    return {"message": f"Restored to version {version_number}", "id": str(item_id)}


@router.get("/versions/{entity_type}/{entity_id}")
async def get_versions(
    entity_type: str, entity_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    versioning = VersioningService(db)
    versions = await versioning.get_history(entity_type, entity_id)
    return [
        {
            "id": str(v.id), "version_number": v.version_number,
            "change_type": v.change_type, "change_reason": v.change_reason,
            "created_at": v.created_at,
        }
        for v in versions
    ]

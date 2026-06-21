#!/usr/bin/env python
"""Backfill legacy `consolidations` rows into git-backed topic files.

The latest schema no longer keeps the row-shaped `consolidations` table. This
script is intentionally tolerant: if the table is already gone, it exits cleanly.
Run it before applying the drop migration when upgrading an older database that
actually contains rows.
"""

import argparse
import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.context.index import StoreIndexer
from app.context.store.documents import MarkdownSerializer, StoreDocument, safe_slug
from app.context.store.gitstore import GitContextStore
from app.context.store.layout import scaffold_store
from app.database import async_session
from app.models.enums import Pillar
from app.providers.base import EmbeddingProvider
from app.runtime import get_runtime

KNOWN_PILLARS = {pillar.value for pillar in Pillar}
DEFAULT_PILLAR = Pillar.CONTEXT_LAYERS.value


def _first_pillar(value: Any) -> str:
    if isinstance(value, (list, tuple)) and value:
        candidate = str(value[0])
    elif isinstance(value, str) and value:
        candidate = value
    else:
        candidate = DEFAULT_PILLAR
    return candidate if candidate in KNOWN_PILLARS else DEFAULT_PILLAR


def _created_date(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.date().isoformat()
    return datetime.now(timezone.utc).date().isoformat()


def _title_from_insight(insight: str) -> str:
    first_line = " ".join(insight.split()).split(". ", 1)[0]
    return (first_line[:90] or "Legacy consolidation").rstrip(".")


def document_for_legacy_consolidation(row: Mapping[str, Any]) -> StoreDocument:
    insight = " ".join(str(row.get("insight_text") or "").split())
    legacy_id = str(row["id"])
    title = _title_from_insight(insight)
    pillar = _first_pillar(row.get("pillar"))
    slug = safe_slug(f"{title}-{legacy_id[:8]}", fallback=f"legacy-{legacy_id[:8]}")
    created = _created_date(row.get("created_at"))
    source_ids = [str(value) for value in (row.get("connected_source_ids") or [])]
    thought_ids = [str(value) for value in (row.get("connected_thought_ids") or [])]
    confidence = float(row.get("confidence") or 0.5)

    refs = [f"[source:{sid}]" for sid in source_ids]
    refs.extend(f"[thought:{tid}]" for tid in thought_ids)
    citation = " ".join(refs)
    claim = f"- {insight}{(' ' + citation) if citation else ''}"

    front = {
        "id": f"topic-{slug}",
        "pillar": pillar,
        "type": "topic",
        "status": "active",
        "confidence": round(max(0.0, min(confidence, 1.0)), 2),
        "priority": round(max(0.3, min(confidence, 0.8)), 2),
        "visibility": "private",
        "freshness": created,
        "last_consolidated": created,
        "sources": source_ids,
        "legacy_thoughts": thought_ids,
        "legacy_consolidation_id": legacy_id,
        "related": [],
    }
    body = (
        f"# {title}\n\n"
        f"## Gist\n\n{insight[:600]}\n\n"
        f"## Key claims\n\n{claim}\n\n"
        "## Tensions\n\n"
        "## Implications\n\n"
        "Migrated from the legacy consolidations table.\n"
    )
    return StoreDocument(path=f"knowledge/{pillar}/{slug}.md", front=front, body=body)


async def _legacy_table_exists(db: AsyncSession) -> bool:
    result = await db.execute(text("SELECT to_regclass('public.consolidations')"))
    return result.scalar_one_or_none() is not None


async def _legacy_rows(db: AsyncSession, limit: int | None = None) -> list[Mapping[str, Any]]:
    limit_clause = "LIMIT :limit" if limit else ""
    result = await db.execute(
        # B608: the only interpolation is a fixed optional LIMIT clause; the value
        # is still bound below.
        text(
            f"""
            SELECT id, insight_text, connected_source_ids, connected_thought_ids,
                   pillar, confidence, consolidation_type, created_at
            FROM consolidations
            ORDER BY created_at, id
            {limit_clause}
            """  # nosec B608
        ),
        {"limit": limit} if limit else {},
    )
    return list(result.mappings().all())


async def backfill_legacy_consolidations(
    db: AsyncSession,
    store: GitContextStore,
    embedder: EmbeddingProvider | None,
    limit: int | None = None,
    skip_index: bool = False,
) -> dict:
    await scaffold_store(store)
    if not await _legacy_table_exists(db):
        return {"backfilled": 0, "files": [], "reason": "legacy table not found"}

    rows = await _legacy_rows(db, limit=limit)
    if not rows:
        return {"backfilled": 0, "files": [], "reason": "legacy table empty"}

    serializer = MarkdownSerializer()
    files = {}
    for row in rows:
        document = document_for_legacy_consolidation(row)
        files[document.path] = serializer.dumps(document)

    await store.commit(files, f"backfill: migrate {len(files)} legacy consolidations")
    if embedder is not None and not skip_index:
        await StoreIndexer(db, store, embedder).sync()
    return {"backfilled": len(files), "files": sorted(files), "reason": "ok"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill legacy consolidations rows into context topic files."
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--store-path", default=None, help="Defaults to CONTEXT_STORE_PATH.")
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Write files but skip context_sections re-indexing.",
    )
    return parser


async def _main() -> int:
    args = _parser().parse_args()
    store = GitContextStore(args.store_path or settings.context_store_path)
    embedder = None
    if not args.skip_index:
        runtime = await get_runtime()
        embedder = runtime.embedder
    async with async_session() as db:
        result = await backfill_legacy_consolidations(
            db, store, embedder, limit=args.limit, skip_index=args.skip_index
        )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))

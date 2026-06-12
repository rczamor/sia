"""Store indexing: sync files into context_sections and generate INDEX.md.

INDEX.md is the priority map the ContextBuilder reads first: every topic and skill
ordered by priority × freshness decay, with gists and token estimates. The Postgres
rows exist for similarity search and joins; the files stay canonical, so the whole
table can be rebuilt from the store at any time.
"""

import hashlib
import logging
import math
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.store.documents import MarkdownSerializer, StoreDocument, estimate_tokens
from app.context.store.gitstore import GitContextStore
from app.models.tables import ContextSections
from app.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

FRESHNESS_HALF_LIFE_DAYS = 30.0
INDEXED_PREFIXES = ("knowledge/", "skills/", "profile/", "theses/", "tensions/")


def freshness_decay(freshness: datetime | None, now: datetime | None = None) -> float:
    if freshness is None:
        return 0.5
    now = now or datetime.now(timezone.utc)
    if freshness.tzinfo is None:
        freshness = freshness.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - freshness).total_seconds() / 86400)
    return math.pow(0.5, age_days / FRESHNESS_HALF_LIFE_DAYS)


def _parse_freshness(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class StoreIndexer:
    def __init__(self, db: AsyncSession, store: GitContextStore, embedder: EmbeddingProvider):
        self.db = db
        self.store = store
        self.embedder = embedder
        self.serializer = MarkdownSerializer()

    async def sync(self, regenerate_index: bool = True) -> list[str]:
        """Re-index every store file; returns the list of indexed paths."""
        head = await self.store.head_sha()
        paths = [
            p
            for p in await self.store.list_paths()
            if p.endswith(".md") and p.startswith(INDEXED_PREFIXES)
        ]

        indexed: list[str] = []
        for path in paths:
            text = await self.store.read(path)
            if text is None:
                continue
            document = self.serializer.loads(path, text)
            await self._upsert(document, head)
            indexed.append(path)

        # drop rows for files that no longer exist
        existing = (await self.db.execute(select(ContextSections.path))).scalars().all()
        stale = set(existing) - set(indexed)
        if stale:
            await self.db.execute(delete(ContextSections).where(ContextSections.path.in_(stale)))
        await self.db.commit()

        if regenerate_index:
            await self.write_index_md()
        return indexed

    async def _upsert(self, document: StoreDocument, commit_sha: str) -> None:
        serialized = self.serializer.dumps(document)
        content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

        row = await self.db.get(ContextSections, document.path)
        if row is not None and row.content_hash == content_hash:
            # Unchanged file: do NOT re-embed or touch the row. This keeps updated_at
            # stable (so "recently changed" actually means changed) and avoids
            # re-embedding the whole store on every sync.
            return

        front = document.front
        gist = document.section("Gist") or document.body.strip()[:400]
        title = front.get("title") or _title_from(document)
        embed_text = f"{title}\n{gist}"[:4000]
        embedding = await self.embedder.embed(embed_text)

        values = {
            "kind": document.kind,
            "title": title,
            "pillar": front.get("pillar"),
            "status": str(front.get("status", "active")),
            "priority": float(front.get("priority", 0.5)),
            "confidence": float(front.get("confidence", 0.5)),
            "visibility": str(front.get("visibility", "private")),
            "freshness": _parse_freshness(front.get("freshness")),
            "gist": gist,
            "token_estimate": estimate_tokens(serialized),
            "embedding": embedding,
            "commit_sha": commit_sha,
            "content_hash": content_hash,
        }
        if row is None:
            self.db.add(ContextSections(path=document.path, **values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await self.db.flush()

    async def write_index_md(self) -> str:
        rows = (
            (
                await self.db.execute(
                    select(ContextSections).where(ContextSections.kind.in_(["topic", "skill"]))
                )
            )
            .scalars()
            .all()
        )
        now = datetime.now(timezone.utc)
        ranked = sorted(
            rows, key=lambda r: r.priority * freshness_decay(r.freshness, now), reverse=True
        )

        lines = [
            "# INDEX",
            "",
            f"Generated {now.date().isoformat()} — priority × freshness order. Do not edit.",
            "",
            "| file | kind | pillar | score | tokens | gist |",
            "|---|---|---|---|---|---|",
        ]
        for row in ranked:
            if row.status == "archived":
                continue
            score = row.priority * freshness_decay(row.freshness, now)
            gist_one_line = " ".join((row.gist or "").split())[:140]
            lines.append(
                f"| {row.path} | {row.kind} | {row.pillar or '-'} | {score:.2f} "
                f"| {row.token_estimate} | {gist_one_line} |"
            )
        content = "\n".join(lines) + "\n"
        return await self.store.commit({"INDEX.md": content}, "chore: regenerate INDEX")


def _title_from(document: StoreDocument) -> str:
    for line in document.body.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return document.path.rsplit("/", 1)[-1].removesuffix(".md").replace("-", " ")

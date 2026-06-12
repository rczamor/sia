import uuid
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import (
    Consolidations,
    ExpertiseArtifacts,
    MyThoughts,
    SourceContent,
)
from app.providers.base import EmbeddingProvider

# Table lookup for dynamic access
TABLE_MAP = {
    "source_content": SourceContent,
    "my_thoughts": MyThoughts,
    "expertise_artifacts": ExpertiseArtifacts,
    "consolidations": Consolidations,
}


class KnowledgeStore:
    """Data-layer CRUD for the knowledge base. Search lives in app.retrieval."""

    def __init__(self, db: AsyncSession, embedder: EmbeddingProvider):
        self.db = db
        self.embedder = embedder

    # --- Create ---

    async def add_source(
        self,
        title: str,
        url: str | None = None,
        content: str | None = None,
        summary: str | None = None,
        pillar: list[str] | None = None,
        source_type: str = "article",
        author: str | None = None,
        your_notes: str | None = None,
        tags: list[str] | None = None,
        trust_tier: str = "untrusted",
    ) -> SourceContent:
        embed_text = f"{title} {summary or ''} {content or ''}"[:8000]
        embedding = await self.embedder.embed(embed_text)

        item = SourceContent(
            title=title,
            url=url,
            content=content,
            summary=summary,
            pillar=pillar or [],
            source_type=source_type,
            author=author,
            your_notes=your_notes,
            tags=tags or [],
            trust_tier=trust_tier,
            embedding=embedding,
        )
        self.db.add(item)
        await self.db.flush()
        return item

    async def add_thought(
        self,
        content: str,
        pillar: list[str] | None = None,
        thought_type: str = "idea",
        related_source_ids: list[uuid.UUID] | None = None,
        maturity: str = "raw",
    ) -> MyThoughts:
        embedding = await self.embedder.embed(content[:8000])

        item = MyThoughts(
            content=content,
            pillar=pillar or [],
            thought_type=thought_type,
            related_source_ids=related_source_ids or [],
            maturity=maturity,
            embedding=embedding,
        )
        self.db.add(item)
        await self.db.flush()
        return item

    async def add_artifact(
        self,
        title: str,
        content: str,
        artifact_type: str = "framework",
        domain: str | None = None,
        pillar: list[str] | None = None,
    ) -> ExpertiseArtifacts:
        embed_text = f"{title} {content}"[:8000]
        embedding = await self.embedder.embed(embed_text)

        item = ExpertiseArtifacts(
            title=title,
            content=content,
            artifact_type=artifact_type,
            domain=domain,
            pillar=pillar or [],
            embedding=embedding,
        )
        self.db.add(item)
        await self.db.flush()
        return item

    # --- Read ---

    async def get_item(self, table_name: str, item_id: uuid.UUID) -> Any | None:
        table = TABLE_MAP.get(table_name)
        if not table:
            return None
        result = await self.db.execute(select(table).where(table.id == item_id))
        return result.scalar_one_or_none()

    async def list_items(
        self,
        table_name: str,
        pillar: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Any]:
        table = TABLE_MAP.get(table_name)
        if not table:
            return []
        query = select(table)
        if pillar:
            query = query.where(table.pillar.overlap(pillar))
        query = query.order_by(table.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # --- Update ---

    async def update_item(self, table_name: str, item_id: uuid.UUID, updates: dict) -> Any | None:
        table = TABLE_MAP.get(table_name)
        if not table:
            return None

        # Re-embed if content fields changed
        re_embed = False
        if table_name == "source_content" and ("title" in updates or "content" in updates or "summary" in updates):
            re_embed = True
        elif table_name == "my_thoughts" and "content" in updates:
            re_embed = True
        elif table_name == "expertise_artifacts" and ("title" in updates or "content" in updates):
            re_embed = True

        if re_embed:
            item = await self.get_item(table_name, item_id)
            if item:
                if table_name == "source_content":
                    t = updates.get("title", item.title)
                    s = updates.get("summary", item.summary or "")
                    c = updates.get("content", item.content or "")
                    embed_text = f"{t} {s} {c}"[:8000]
                elif table_name == "my_thoughts":
                    embed_text = updates.get("content", item.content)[:8000]
                else:
                    t = updates.get("title", item.title)
                    c = updates.get("content", item.content)
                    embed_text = f"{t} {c}"[:8000]
                updates["embedding"] = await self.embedder.embed(embed_text)

        stmt = update(table).where(table.id == item_id).values(**updates).returning(table)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.scalar_one_or_none()

    # --- Delete ---

    async def delete_item(self, table_name: str, item_id: uuid.UUID) -> bool:
        table = TABLE_MAP.get(table_name)
        if not table:
            return False
        stmt = delete(table).where(table.id == item_id)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount > 0

    # --- Dedup check ---

    async def url_exists(self, url: str) -> bool:
        result = await self.db.execute(
            select(SourceContent.id).where(SourceContent.url == url)
        )
        return result.scalar_one_or_none() is not None

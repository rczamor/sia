import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import (
    AiConfig,
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
    """Core service for knowledge base CRUD and hybrid search."""

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

    # --- Hybrid Search ---

    async def hybrid_search(
        self,
        query: str,
        tables: list[str] | None = None,
        pillar: list[str] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 20,
    ) -> list[dict]:
        # Get search config
        config_result = await self.db.execute(
            select(AiConfig).where(AiConfig.config_key == "hybrid_search")
        )
        config_row = config_result.scalar_one_or_none()
        if config_row:
            cfg = config_row.config_value
            semantic_weight = cfg.get("semantic_weight", 0.7)
            keyword_weight = cfg.get("keyword_weight", 0.3)
            threshold = cfg.get("similarity_threshold", 0.3)
        else:
            semantic_weight = 0.7
            keyword_weight = 0.3
            threshold = 0.3

        # Generate query embedding
        query_embedding = await self.embedder.embed(query)

        search_tables = tables or ["source_content", "my_thoughts", "expertise_artifacts", "consolidations"]
        all_results = []

        for table_name in search_tables:
            table = TABLE_MAP.get(table_name)
            if not table:
                continue

            # Build the title/content_preview select based on table
            if table_name == "source_content":
                title_col = "title"
                preview_col = "summary"
            elif table_name == "my_thoughts":
                title_col = "NULL"
                preview_col = "LEFT(content, 200)"
            elif table_name == "expertise_artifacts":
                title_col = "title"
                preview_col = "LEFT(content, 200)"
            elif table_name == "consolidations":
                title_col = "NULL"
                preview_col = "LEFT(insight_text, 200)"
            else:
                continue

            # Pillar filter
            pillar_clause = ""
            if pillar:
                pillar_array = "{" + ",".join(pillar) + "}"
                pillar_clause = f"AND pillar && '{pillar_array}'::text[]"

            # Date filter
            date_clause = ""
            if date_from:
                date_clause += f" AND created_at >= '{date_from.isoformat()}'"
            if date_to:
                date_clause += f" AND created_at <= '{date_to.isoformat()}'"

            sql = text(f"""
                WITH semantic AS (
                    SELECT id, {title_col} as title, {preview_col} as content_preview,
                           pillar, created_at,
                           1 - (embedding <=> :query_vec::vector) as semantic_score
                    FROM {table_name}
                    WHERE embedding IS NOT NULL
                    AND 1 - (embedding <=> :query_vec::vector) > :threshold
                    {pillar_clause}
                    {date_clause}
                ),
                keyword AS (
                    SELECT id, ts_rank_cd(search_vector, plainto_tsquery('english', :query_text)) as keyword_score
                    FROM {table_name}
                    WHERE search_vector @@ plainto_tsquery('english', :query_text)
                )
                SELECT s.id, s.title, s.content_preview, s.pillar, s.created_at,
                       COALESCE(s.semantic_score, 0) * :sem_w + COALESCE(k.keyword_score, 0) * :kw_w as score
                FROM semantic s
                LEFT JOIN keyword k ON s.id = k.id
                ORDER BY score DESC
                LIMIT :lim
            """)

            result = await self.db.execute(
                sql,
                {
                    "query_vec": str(query_embedding),
                    "query_text": query,
                    "threshold": threshold,
                    "sem_w": semantic_weight,
                    "kw_w": keyword_weight,
                    "lim": limit,
                },
            )

            for row in result.mappings().all():
                all_results.append({
                    "id": row["id"],
                    "entity_type": table_name,
                    "title": row["title"],
                    "content_preview": row["content_preview"],
                    "pillar": row["pillar"] or [],
                    "score": float(row["score"]),
                    "created_at": row["created_at"],
                })

        # Sort all results by score descending and limit
        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results[:limit]

    # --- Dedup check ---

    async def url_exists(self, url: str) -> bool:
        result = await self.db.execute(
            select(SourceContent.id).where(SourceContent.url == url)
        )
        return result.scalar_one_or_none() is not None

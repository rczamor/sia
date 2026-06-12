"""Retrieval layer — reach into the Data layer.

Hybrid search: BM25 (Postgres full-text) and dense (pgvector cosine) rankings per
table, fused with Reciprocal Rank Fusion. RRF combines *rankings*, never raw scores,
so results from heterogeneous scorers and tables are directly comparable — the
weighted-sum approach this replaces mixed bounded cosine similarities with unbounded
ts_rank_cd values and produced meaningless cross-table ordering.

This module contains no business logic: it takes a query, reaches, and returns
ranked rows.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import AiConfig
from app.providers.base import EmbeddingProvider

# Table name -> SQL fragments for display columns and an always-applied safety
# filter. Names/fragments are hardcoded here and are the only non-parameterized
# strings in the query. `safety` excludes quarantined (prompt-injection-flagged)
# rows so the served retrieval path honors the same exclusion as consolidation —
# only source_content carries the quarantined column.
SEARCHABLE_TABLES: dict[str, dict[str, str]] = {
    "source_content": {
        "title": "title",
        "preview": "summary",
        "safety": "AND quarantined IS FALSE",
    },
    "my_thoughts": {"title": "NULL", "preview": "LEFT(content, 200)", "safety": ""},
    "expertise_artifacts": {"title": "title", "preview": "LEFT(content, 200)", "safety": ""},
}

DEFAULT_RRF_K = 60
DEFAULT_CANDIDATES_PER_TABLE = 50
DEFAULT_MIN_SIMILARITY = 0.1  # dense-side cosine floor; tune per embedding model

_SEARCH_SQL = """
WITH dense AS (
    SELECT id, {title} AS title, {preview} AS content_preview, pillar, created_at,
           ROW_NUMBER() OVER (
               ORDER BY embedding <=> CAST(:query_vec AS vector)
           ) AS rnk
    FROM {table}
    WHERE embedding IS NOT NULL
      AND 1 - (embedding <=> CAST(:query_vec AS vector)) >= :min_similarity
    {safety}
    {filters}
    ORDER BY embedding <=> CAST(:query_vec AS vector)
    LIMIT :candidates
),
keyword AS (
    SELECT id, {title} AS title, {preview} AS content_preview, pillar, created_at,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank_cd(search_vector, plainto_tsquery('english', :query_text)) DESC
           ) AS rnk
    FROM {table}
    WHERE search_vector @@ plainto_tsquery('english', :query_text)
    {safety}
    {filters}
    ORDER BY ts_rank_cd(search_vector, plainto_tsquery('english', :query_text)) DESC
    LIMIT :candidates
)
SELECT COALESCE(d.id, k.id) AS id,
       COALESCE(d.title, k.title) AS title,
       COALESCE(d.content_preview, k.content_preview) AS content_preview,
       COALESCE(d.pillar, k.pillar) AS pillar,
       COALESCE(d.created_at, k.created_at) AS created_at,
       d.rnk AS dense_rank,
       k.rnk AS keyword_rank
FROM dense d
FULL OUTER JOIN keyword k ON d.id = k.id
"""


class SearchService:
    """Hybrid retrieval over the Data layer with RRF fusion."""

    def __init__(self, db: AsyncSession, embedder: EmbeddingProvider):
        self.db = db
        self.embedder = embedder

    async def _config(self) -> dict[str, Any]:
        row = (
            await self.db.execute(select(AiConfig).where(AiConfig.config_key == "retrieval"))
        ).scalar_one_or_none()
        value = row.config_value if row else {}
        return {
            "rrf_k": value.get("rrf_k", DEFAULT_RRF_K),
            "candidates_per_table": value.get(
                "candidates_per_table", DEFAULT_CANDIDATES_PER_TABLE
            ),
            # Relevance floor on the dense side: rows below this cosine similarity
            # are excluded so off-topic queries don't return nearest-but-unrelated
            # noise (keyword matches still surface independently).
            "min_similarity": value.get("min_similarity", DEFAULT_MIN_SIMILARITY),
        }

    async def search(
        self,
        query: str,
        tables: list[str] | None = None,
        pillar: list[str] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 20,
    ) -> list[dict]:
        config = await self._config()
        rrf_k = config["rrf_k"]
        query_embedding = await self.embedder.embed(query)

        if tables is not None:
            unknown = [t for t in tables if t not in SEARCHABLE_TABLES]
            if unknown:
                raise ValueError(
                    f"Unknown search tables {unknown}; valid: {sorted(SEARCHABLE_TABLES)}"
                )
        search_tables = list(tables) if tables else list(SEARCHABLE_TABLES)

        filters = ""
        if pillar:
            filters += " AND pillar && CAST(:pillar_filter AS varchar[])"
        if date_from:
            filters += " AND created_at >= :date_from"
        if date_to:
            filters += " AND created_at <= :date_to"

        params: dict[str, Any] = {
            "query_vec": str(query_embedding),
            "query_text": query,
            "candidates": config["candidates_per_table"],
            "min_similarity": config["min_similarity"],
        }
        if pillar:
            params["pillar_filter"] = pillar
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to

        fused: list[dict] = []
        for table_name in search_tables:
            columns = SEARCHABLE_TABLES[table_name]
            sql = text(
                _SEARCH_SQL.format(
                    table=table_name,
                    title=columns["title"],
                    preview=columns["preview"],
                    safety=columns["safety"],
                    filters=filters,
                )
            )
            result = await self.db.execute(sql, params)
            for row in result.mappings():
                score = 0.0
                if row["dense_rank"] is not None:
                    score += 1.0 / (rrf_k + row["dense_rank"])
                if row["keyword_rank"] is not None:
                    score += 1.0 / (rrf_k + row["keyword_rank"])
                fused.append(
                    {
                        "id": row["id"],
                        "entity_type": table_name,
                        "title": row["title"],
                        "content_preview": row["content_preview"],
                        "pillar": row["pillar"] or [],
                        "score": score,
                        "created_at": row["created_at"],
                    }
                )

        fused.sort(key=lambda r: r["score"], reverse=True)
        return fused[:limit]

"""Retrieval eval harness: recall@5 for RRF fusion vs the legacy weighted-sum.

Seeds a deterministic 40-doc corpus into the target database (use a scratch DB!),
runs 20 queries with known relevant documents, and reports recall@5 for:
  a) the live Retrieval layer (RRF fusion), and
  b) the legacy formula it replaced (semantic*0.7 + ts_rank_cd*0.3, threshold 0.3).

    DATABASE_URL=postgresql+asyncpg://...sia_eval python scripts/retrieval_eval.py
"""

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import async_session  # noqa: E402
from app.data.knowledge_store import KnowledgeStore  # noqa: E402
from app.retrieval.search import SearchService  # noqa: E402
from tests.fakes import HashingEmbedder  # noqa: E402

TOPICS = [
    ("RRF fusion for hybrid retrieval", "Reciprocal rank fusion merges keyword and vector rankings without mixing raw scores.", "reciprocal rank fusion ranking"),
    ("Sleep consolidation in the brain", "Hippocampal replay extracts schemas and prunes noise during slow-wave sleep.", "sleep schema extraction hippocampus"),
    ("JTBD interviews for product teams", "Jobs to be done interviews uncover the customer struggle behind demand.", "jobs to be done customer interviews"),
    ("Postgres HNSW index tuning", "HNSW parameters m and ef_construction trade recall for build time in pgvector.", "pgvector hnsw recall tuning"),
    ("Executive communication patterns", "Leaders compress detail into decision-ready narratives for boards.", "board narratives executive communication"),
    ("Context windows and attention budget", "Long context degrades attention; selection beats raw capacity.", "context window attention degradation"),
    ("Vector embeddings for semantic search", "Dense embeddings capture meaning that keyword matching misses.", "dense embeddings semantic meaning"),
    ("Growth experiments that compound", "Sequential experiment design compounds learning across product bets.", "compounding growth experiment design"),
    ("Memory consolidation for agents", "Background consolidation merges redundant agent memories and prunes stale facts.", "agent memory consolidation pruning"),
    ("Prompt injection defenses", "Quarantine untrusted content and gate writes behind reviewed diffs.", "prompt injection quarantine defense"),
    ("Token budgets in context assembly", "Greedy selection under a token budget with priority and freshness weighting.", "token budget greedy selection"),
    ("Knowledge graphs in plain Postgres", "Subject predicate object triples with recursive CTEs avoid a graph database.", "postgres triples recursive cte graph"),
    ("Decision-ready context artifacts", "A cited, scored, budget-shaped artifact beats raw retrieval chunks.", "cited scored context artifact"),
    ("Reciprocal rank fusion constants", "The k constant dampens the head of each ranking; sixty is the common default.", "rrf k constant sixty"),
    ("Bounded rationality and satisficing", "Simon argued decision makers satisfice under bounded information.", "simon bounded rationality satisficing"),
    ("Fast and frugal heuristics", "Take-the-best outperforms regression while using fewer cues.", "take the best heuristic fewer cues"),
    ("Schema extraction during encoding", "Experts encode gist representations rather than raw detail.", "gist schema expert encoding"),
    ("MCP connectors for agent harnesses", "A streamable HTTP MCP server plugs context into any harness.", "mcp server harness connector"),
    ("Freshness decay in ranking", "Stale knowledge decays in priority unless re-cited by recent builds.", "freshness decay stale priority"),
    ("Lineage and audit trails", "Every model call records prompts, tokens, cost, and outputs for replay.", "lineage audit model call replay"),
]

LEGACY_SQL = """
WITH semantic AS (
    SELECT id, 1 - (embedding <=> CAST(:query_vec AS vector)) AS semantic_score
    FROM expertise_artifacts
    WHERE embedding IS NOT NULL
      AND 1 - (embedding <=> CAST(:query_vec AS vector)) > 0.3
),
keyword AS (
    SELECT id, ts_rank_cd(search_vector, plainto_tsquery('english', :query_text)) AS keyword_score
    FROM expertise_artifacts
    WHERE search_vector @@ plainto_tsquery('english', :query_text)
)
SELECT s.id, COALESCE(s.semantic_score, 0) * 0.7 + COALESCE(k.keyword_score, 0) * 0.3 AS score
FROM semantic s LEFT JOIN keyword k ON s.id = k.id
ORDER BY score DESC LIMIT 5
"""


async def main() -> int:
    if "eval" not in os.environ.get("DATABASE_URL", "") and "test" not in os.environ.get(
        "DATABASE_URL", ""
    ):
        print("Refusing to seed: DATABASE_URL must point at an eval/test database")
        return 1

    embedder = HashingEmbedder()
    async with async_session() as db:
        await db.execute(text("TRUNCATE expertise_artifacts CASCADE"))
        store = KnowledgeStore(db, embedder)
        ids = []
        for title, content, _ in TOPICS:
            item = await store.add_artifact(title=title, content=content, pillar=["context_layers"])
            ids.append(item.id)
        # 20 distractor docs
        for i in range(20):
            await store.add_artifact(
                title=f"Distractor note {i}",
                content=f"Miscellaneous unrelated filler text number {i} about weather and lunch.",
                pillar=["leadership"],
            )
        await db.commit()

        rrf_hits = legacy_hits = 0
        service = SearchService(db, embedder)
        for (title, content, query), doc_id in zip(TOPICS, ids):
            results = await service.search(query=query, tables=["expertise_artifacts"], limit=5)
            if doc_id in [r["id"] for r in results]:
                rrf_hits += 1

            query_vec = str(await embedder.embed(query))
            rows = await db.execute(
                text(LEGACY_SQL), {"query_vec": query_vec, "query_text": query}
            )
            if doc_id in [row.id for row in rows]:
                legacy_hits += 1

    n = len(TOPICS)
    print(f"recall@5 over {n} queries")
    print(f"  RRF fusion (live):        {rrf_hits}/{n} = {rrf_hits / n:.2f}")
    print(f"  legacy weighted-sum:      {legacy_hits}/{n} = {legacy_hits / n:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

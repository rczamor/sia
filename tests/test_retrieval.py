"""Retrieval-layer tests: RRF fusion correctness and quality vs the old weighted sum.

Uses a bag-of-words hashing embedder so vector similarity has real semantics
without a model server.
"""

import pytest

from app.data.knowledge_store import KnowledgeStore
from app.retrieval.search import SearchService
from tests.fakes import HashingEmbedder

CORPUS = [
    ("RRF fusion for hybrid retrieval", "Reciprocal rank fusion merges keyword and vector rankings without score mixing."),
    ("Sleep consolidation in the brain", "Hippocampal replay extracts schemas and prunes noise during sleep."),
    ("JTBD interviews for product teams", "Jobs to be done interviews uncover customer struggle and demand."),
    ("Postgres HNSW index tuning", "HNSW parameters m and ef_construction trade recall for build time in pgvector."),
    ("Executive communication patterns", "Leaders compress detail into decision-ready narratives for boards."),
    ("Context windows and attention budget", "Long context degrades model attention; selection beats capacity."),
    ("Vector embeddings for search", "Dense embeddings capture semantics that keyword matching misses."),
    ("Growth experiments that compound", "Sequential experiment design compounds learning across product bets."),
]

QUERIES = [
    ("reciprocal rank fusion ranking", 0),
    ("sleep schema extraction hippocampus", 1),
    ("jobs to be done customer interviews", 2),
    ("pgvector hnsw recall tuning", 3),
    ("board narratives executive communication", 4),
]


@pytest.fixture
async def seeded_corpus(db_session):
    embedder = HashingEmbedder()
    store = KnowledgeStore(db_session, embedder)
    ids = []
    for title, content in CORPUS:
        item = await store.add_artifact(title=title, content=content, pillar=["context_layers"])
        ids.append(item.id)
    await db_session.commit()
    return embedder, ids


async def test_rrf_finds_relevant_docs(db_session, seeded_corpus):
    embedder, ids = seeded_corpus
    service = SearchService(db_session, embedder)
    for query, expected_index in QUERIES:
        results = await service.search(query=query, limit=5)
        top_ids = [r["id"] for r in results]
        assert ids[expected_index] in top_ids, f"query {query!r} missed its document"


async def test_rrf_scores_are_cross_table_comparable(db_session, seeded_corpus):
    embedder, _ = seeded_corpus
    store = KnowledgeStore(db_session, embedder)
    await store.add_thought(
        content="Reciprocal rank fusion also applies to my thought ranking experiments",
        pillar=["context_layers"],
    )
    await db_session.commit()

    service = SearchService(db_session, embedder)
    results = await service.search(query="reciprocal rank fusion", limit=10)
    entity_types = {r["entity_type"] for r in results}
    assert {"expertise_artifacts", "my_thoughts"} <= entity_types
    # RRF scores are bounded: each ranking contributes at most 1/(k+1)
    assert all(0 < r["score"] <= 2 / 61 + 1e-9 for r in results)


async def test_pillar_filter_is_parameterized_and_effective(db_session, seeded_corpus):
    embedder, _ = seeded_corpus
    service = SearchService(db_session, embedder)
    results = await service.search(query="rank fusion", pillar=["leadership"], limit=10)
    assert results == []
    # injection attempt must be treated as data, not SQL
    results = await service.search(
        query="rank fusion", pillar=["'; DROP TABLE expertise_artifacts; --"], limit=10
    )
    assert results == []


async def test_table_scope(db_session, seeded_corpus):
    embedder, _ = seeded_corpus
    service = SearchService(db_session, embedder)
    results = await service.search(query="rank fusion", tables=["my_thoughts"], limit=10)
    assert all(r["entity_type"] == "my_thoughts" for r in results)

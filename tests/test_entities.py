"""Entity resolution + extraction: semantic dedup, alias merge, entity relations,
and the indexer content-hash change-detection."""

from sqlalchemy import text

from app.context.entities import EntityExtractor, EntityService
from app.context.index import StoreIndexer
from tests.fakes import FakeLLM, HashingEmbedder


async def test_exact_name_dedup_reinforces(db_session):
    svc = EntityService(db_session, HashingEmbedder())
    a = await svc.resolve_or_create("Reciprocal Rank Fusion", "concept")
    b = await svc.resolve_or_create("Reciprocal Rank Fusion", "concept")
    await db_session.commit()
    assert a.id == b.id
    assert a.created and not b.created
    row = (
        await db_session.execute(
            text("SELECT mention_count, confidence FROM entities WHERE id = :id"), {"id": str(a.id)}
        )
    ).first()
    assert row.mention_count == 2  # reinforced
    assert row.confidence > 0.5


async def test_semantic_merge_records_alias(db_session):
    """A different surface form of the same concept merges into one entity as an
    alias rather than fragmenting into a second node."""
    svc = EntityService(db_session, HashingEmbedder())
    first = await svc.resolve_or_create("Reciprocal Rank Fusion", "concept")
    # same tokens, different case → identical embedding → semantic match
    second = await svc.resolve_or_create("reciprocal rank fusion", "concept")
    await db_session.commit()

    assert second.id == first.id  # merged, not a new node
    assert await svc.count() == 1
    aliases = (
        await db_session.execute(
            text("SELECT aliases FROM entities WHERE id = :id"), {"id": str(first.id)}
        )
    ).scalar()
    assert "reciprocal rank fusion" in aliases


async def test_declared_alias_attaches_not_fragments(db_session):
    """An LLM-declared alias whose embedding is dissimilar to the canonical name
    (acronym vs expansion, cosine 0.0) must still attach as an alias — and a later
    lookup of that surface form must resolve to the SAME entity, not a new node."""
    svc = EntityService(db_session, HashingEmbedder())
    rrf = await svc.resolve_or_create(
        "RRF", "method", aliases=["reciprocal rank fusion"]
    )
    await db_session.commit()
    assert await svc.count() == 1
    aliases = (
        await db_session.execute(
            text("SELECT aliases FROM entities WHERE id = :id"), {"id": str(rrf.id)}
        )
    ).scalar()
    assert "reciprocal rank fusion" in aliases

    # the expansion now resolves to the same entity via the alias index
    again = await svc.resolve_or_create("reciprocal rank fusion", "concept")
    await db_session.commit()
    assert again.id == rrf.id
    assert await svc.count() == 1


async def test_extractor_attaches_declared_aliases(db_session, store):
    from app.data.lineage import LineageService, TrackedLLMProvider

    await store.commit(
        {"knowledge/context_layers/rrf.md": "---\npillar: context_layers\n---\n\n# RRF\n\n## Gist\n\nRRF.\n"},
        "seed",
    )
    embedder = HashingEmbedder()
    await StoreIndexer(db_session, store, embedder).sync()

    class Row:
        path, gist, kind, status = "knowledge/context_layers/rrf.md", "RRF.", "topic", "active"

    llm = FakeLLM({
        "entities": [{"name": "RRF", "type": "method",
                      "aliases": ["reciprocal rank fusion", "rank fusion"],
                      "mentioned_in": ["knowledge/context_layers/rrf.md"]}],
        "relations": [],
    })
    extractor = EntityExtractor(
        db_session, store, TrackedLLMProvider(llm, LineageService(db_session)), embedder
    )
    import uuid as uuid_module

    added = await extractor.extract_for_topics([Row()], uuid_module.uuid4())
    await db_session.commit()
    assert added == 1  # one entity, two aliases — not three nodes
    assert await EntityService(db_session, embedder).count() == 1


async def test_distinct_concepts_stay_separate(db_session):
    svc = EntityService(db_session, HashingEmbedder())
    await svc.resolve_or_create("Reciprocal Rank Fusion", "concept")
    await svc.resolve_or_create("Sleep Consolidation Pipeline", "concept")
    await db_session.commit()
    assert await svc.count() == 2


async def test_extractor_creates_mentions_and_relations(db_session, store):
    """EntityExtractor writes topic->entity mentions and typed entity<->entity
    relations (with the relation phrase in the edge label)."""
    topic = """---
id: topic-rrf
pillar: context_layers
priority: 0.9
visibility: public
freshness: 2026-06-10
---

# RRF Fusion

## Gist

Reciprocal rank fusion, introduced by Cormack, merges rankings.

## Key claims

- RRF avoids score mixing [source:11111111-1111-1111-1111-111111111111]
"""
    await store.commit({"knowledge/context_layers/rrf.md": topic}, "seed")
    embedder = HashingEmbedder()
    indexed = await StoreIndexer(db_session, store, embedder).sync()
    rows_q = await db_session.execute(
        text("SELECT path, gist, kind, status FROM context_sections WHERE kind='topic'")
    )

    class Row:
        def __init__(self, m):
            self.path, self.gist, self.kind, self.status = m["path"], m["gist"], m["kind"], m["status"]

    rows = [Row(m) for m in rows_q.mappings()]

    llm = FakeLLM({
        "entities": [
            {"name": "RRF", "type": "method", "aliases": ["reciprocal rank fusion"],
             "mentioned_in": ["knowledge/context_layers/rrf.md"]},
            {"name": "Cormack", "type": "person", "aliases": [],
             "mentioned_in": ["knowledge/context_layers/rrf.md"]},
        ],
        "relations": [{"subject": "Cormack", "relation": "authored", "object": "RRF"}],
    })
    from app.data.lineage import LineageService, TrackedLLMProvider

    extractor = EntityExtractor(
        db_session, store, TrackedLLMProvider(llm, LineageService(db_session)), embedder
    )
    import uuid as uuid_module

    added = await extractor.extract_for_topics(rows, uuid_module.uuid4())
    await db_session.commit()
    assert added == 2
    assert "knowledge/context_layers/rrf.md" in indexed

    # topic -> entity mentions edges
    mentions = (
        await db_session.execute(
            text("SELECT count(*) FROM context_edges WHERE predicate='mentions' "
                 "AND object_ref LIKE 'entity:%'")
        )
    ).scalar()
    assert mentions == 2

    # entity -> entity related_to edge with the relation phrase as label
    rel = (
        await db_session.execute(
            text("SELECT label, subject_ref, object_ref FROM context_edges "
                 "WHERE predicate='related_to' AND subject_ref LIKE 'entity:%' "
                 "AND object_ref LIKE 'entity:%'")
        )
    ).first()
    assert rel is not None
    assert rel.label == "authored"


async def test_indexer_skips_unchanged_files(db_session, store):
    """The content-hash skip means a re-sync of an unchanged store does NOT bump
    updated_at (so 'recently changed' is meaningful) and does not re-embed."""
    await store.commit(
        {"knowledge/context_layers/x.md": "---\npillar: context_layers\n---\n\n# X\n\n## Gist\n\nStuff.\n"},
        "seed",
    )
    embedder = HashingEmbedder()
    indexer = StoreIndexer(db_session, store, embedder)
    await indexer.sync()
    before = (
        await db_session.execute(
            text("SELECT updated_at, content_hash FROM context_sections "
                 "WHERE path='knowledge/context_layers/x.md'")
        )
    ).first()
    assert before.content_hash is not None

    # a second sync with no file change must not touch the row
    await indexer.sync()
    after = (
        await db_session.execute(
            text("SELECT updated_at FROM context_sections "
                 "WHERE path='knowledge/context_layers/x.md'")
        )
    ).first()
    assert after.updated_at == before.updated_at

    # changing the file does re-index (updated_at moves)
    await store.commit(
        {"knowledge/context_layers/x.md": "---\npillar: context_layers\n---\n\n# X\n\n## Gist\n\nChanged.\n"},
        "edit",
    )
    await indexer.sync()
    changed = (
        await db_session.execute(
            text("SELECT updated_at FROM context_sections "
                 "WHERE path='knowledge/context_layers/x.md'")
        )
    ).first()
    assert changed.updated_at > before.updated_at

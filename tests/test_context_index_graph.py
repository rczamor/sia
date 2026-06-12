"""Indexer + graph tests: store -> context_sections sync, INDEX.md, edge extraction."""

from sqlalchemy import text

from app.context.graph import GraphService
from app.context.index import StoreIndexer
from app.context.store.documents import MarkdownSerializer, StoreDocument
from tests.fakes import HashingEmbedder

TOPIC_A = """---
id: topic-rrf
pillar: context_layers
priority: 0.9
visibility: public
freshness: 2026-06-10
sources:
  - 11111111-1111-1111-1111-111111111111
related:
  - consolidation-clocks
---

# RRF Fusion

## Gist

Reciprocal rank fusion merges rankings. See [[Consolidation Clocks]].

## Key claims

- RRF avoids score mixing [source:11111111-1111-1111-1111-111111111111]
"""

TOPIC_B = """---
id: topic-clocks
pillar: context_layers
priority: 0.6
---

# Consolidation Clocks

## Gist

Three clocks consolidate knowledge on different cadences.
"""


async def seeded_store(store):
    await store.commit(
        {
            "knowledge/context_layers/rrf-fusion.md": TOPIC_A,
            "knowledge/context_layers/consolidation-clocks.md": TOPIC_B,
        },
        "seed topics",
    )
    return store


async def test_indexer_syncs_sections_and_index(db_session, store):
    await seeded_store(store)
    indexer = StoreIndexer(db_session, store, HashingEmbedder())
    indexed = await indexer.sync()

    assert "knowledge/context_layers/rrf-fusion.md" in indexed
    row = (
        await db_session.execute(
            text("SELECT * FROM context_sections WHERE path = 'knowledge/context_layers/rrf-fusion.md'")
        )
    ).mappings().first()
    assert row["kind"] == "topic"
    assert row["pillar"] == "context_layers"
    assert row["priority"] == 0.9
    assert row["visibility"] == "public"
    assert "Reciprocal rank fusion" in row["gist"]
    assert row["embedding"] is not None

    index_md = await store.read("INDEX.md")
    assert "rrf-fusion.md" in index_md
    # higher priority sorts first
    assert index_md.index("rrf-fusion.md") < index_md.index("consolidation-clocks.md")


async def test_indexer_removes_stale_rows(db_session, store):
    await seeded_store(store)
    indexer = StoreIndexer(db_session, store, HashingEmbedder())
    await indexer.sync()
    await store.commit({"knowledge/context_layers/consolidation-clocks.md": None}, "remove")
    await indexer.sync()
    count = (
        await db_session.execute(text("SELECT count(*) FROM context_sections WHERE kind='topic'"))
    ).scalar()
    assert count == 1


async def test_graph_extracts_declared_edges(db_session, store):
    await seeded_store(store)
    serializer = MarkdownSerializer()
    content = await store.read("knowledge/context_layers/rrf-fusion.md")
    document = serializer.loads("knowledge/context_layers/rrf-fusion.md", content)
    known = await store.list_paths()

    graph = GraphService(db_session)
    count = await graph.sync_document_edges(document, known)
    await db_session.commit()
    assert count == 3  # related_to + derived_from + wikilink mention

    edges = (
        await db_session.execute(
            text("SELECT predicate, object_ref FROM context_edges ORDER BY predicate")
        )
    ).all()
    predicates = [e.predicate for e in edges]
    assert predicates == ["derived_from", "mentions", "related_to"]
    assert any(o.startswith("source:1111") for _, o in edges)
    assert (
        "topic:knowledge/context_layers/consolidation-clocks.md"
        in [o for _, o in edges]
    )


async def test_graph_neighbors_traversal(db_session, store):
    await seeded_store(store)
    graph = GraphService(db_session)
    await graph.upsert_edge("topic:a.md", "related_to", "topic:b.md")
    await graph.upsert_edge("topic:b.md", "mentions", "entity:x")
    await graph.upsert_edge("entity:x", "mentions", "topic:far.md")
    await db_session.commit()

    one_hop = await graph.neighbors(["topic:a.md"], depth=1)
    refs = {e["subject_ref"] for e in one_hop} | {e["object_ref"] for e in one_hop}
    assert "topic:b.md" in refs
    assert "topic:far.md" not in refs

    two_hop = await graph.neighbors(["topic:a.md"], depth=2)
    refs = {e["subject_ref"] for e in two_hop} | {e["object_ref"] for e in two_hop}
    assert "entity:x" in refs


async def test_graph_endpoint_shape(client, db_session, store):
    await seeded_store(store)
    indexer = StoreIndexer(db_session, store, HashingEmbedder())
    await indexer.sync()
    graph = GraphService(db_session)
    serializer = MarkdownSerializer()
    content = await store.read("knowledge/context_layers/rrf-fusion.md")
    await graph.sync_document_edges(
        serializer.loads("knowledge/context_layers/rrf-fusion.md", content),
        await store.list_paths(),
    )
    await db_session.commit()

    response = await client.get("/api/context/graph")
    assert response.status_code == 200
    data = response.json()
    node_ids = {n["id"] for n in data["nodes"]}
    assert "topic:knowledge/context_layers/rrf-fusion.md" in node_ids
    assert all({"source", "target", "predicate"} <= set(e) for e in data["edges"])
    # data-layer refs (source:<uuid>) are not graph-view nodes
    assert not any(n["id"].startswith("source:") for n in data["nodes"])


def test_wikilink_and_section_helpers():
    document = StoreDocument(
        path="knowledge/p/x.md",
        body="## Gist\n\nUses [[Other Topic|alias]] and [[missing#heading]].\n\n## Key claims\n",
    )
    from app.context.graph import WIKILINK_RE

    links = [m.group(1).strip() for m in WIKILINK_RE.finditer(document.body)]
    assert links == ["Other Topic", "missing"]

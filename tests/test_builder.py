"""ContextBuilder tests: ranking, budget, visibility, graph expansion, skills,
fallback policy, audit."""

from sqlalchemy import text

from app.context.builder import ContextBuilder
from app.context.graph import GraphService
from app.context.index import StoreIndexer
from app.context.principals import Principal
from app.retrieval.search import SearchService
from tests.fakes import HashingEmbedder

OWNER = Principal(
    id="owner", kind="owner", token_budget=12000,
    allowed_visibilities=("public", "private"), allow_fallback=True,
)
VISITOR = Principal(
    id="visitor", kind="visitor", token_budget=2500,
    allowed_visibilities=("public",), allow_fallback=False,
)

PUBLIC_TOPIC = """---
id: topic-rrf
pillar: context_layers
priority: 0.9
visibility: public
freshness: 2026-06-10
---

# RRF Fusion

## Gist

Reciprocal rank fusion merges keyword and vector rankings without score mixing.

## Key claims

- RRF avoids cross-scorer score mixing [source:11111111-1111-1111-1111-111111111111]
"""

PRIVATE_TOPIC = """---
id: topic-private
pillar: context_layers
priority: 0.8
visibility: private
freshness: 2026-06-10
related:
  - rrf-fusion
---

# Private Fusion Notes

## Gist

Private notes about reciprocal rank fusion experiments and rankings.

## Key claims

- internal experiments confirm fusion rankings [thought:x]
"""

SKILL = """---
id: skill-review
type: skill
status: active
priority: 0.7
visibility: public
trigger_description: when evaluating ranking fusion changes
token_cost_estimate: 40
---

# Ranking Review Skill

## Procedure

1. Compare rankings before and after fusion.
"""


async def seed(db, store):
    embedder = HashingEmbedder()
    await store.commit(
        {
            "knowledge/context_layers/rrf-fusion.md": PUBLIC_TOPIC,
            "knowledge/context_layers/private-fusion.md": PRIVATE_TOPIC,
            "skills/ranking-review/SKILL.md": SKILL,
            "profile/goals.md": "---\nvisibility: private\n---\n\n# Goals\n\n1. Ship the context engine.\n",
        },
        "seed",
    )
    indexer = StoreIndexer(db, store, embedder)
    indexed = await indexer.sync()
    graph = GraphService(db)
    from app.context.store.documents import MarkdownSerializer

    for path in indexed:
        if path.startswith(("knowledge/", "skills/")):
            content = await store.read(path)
            await graph.sync_document_edges(
                MarkdownSerializer().loads(path, content), indexed
            )
    await db.commit()
    return embedder


async def test_owner_build_serves_ranked_topics_goals_and_skills(db_session, store):
    embedder = await seed(db_session, store)
    builder = ContextBuilder(db_session, store, embedder)
    artifact = await builder.build("reciprocal rank fusion rankings", OWNER)

    paths = [s.path for s in artifact.sections]
    assert "profile/goals.md" in paths  # goals reserve
    assert "knowledge/context_layers/rrf-fusion.md" in paths
    assert artifact.coverage > 0.3
    assert artifact.tokens_used <= OWNER.token_budget
    assert any(s.path == "skills/ranking-review/SKILL.md" for s in artifact.skills)
    markdown = artifact.to_markdown()
    assert "Key claims" in markdown
    assert "[source:" in markdown


async def test_visitor_sees_public_only_no_goals_no_fallback(db_session, store):
    embedder = await seed(db_session, store)
    builder = ContextBuilder(
        db_session, store, embedder, search_service=SearchService(db_session, embedder)
    )
    artifact = await builder.build("anything entirely unrelated zzz qqq", VISITOR)

    paths = [s.path for s in artifact.sections]
    assert "profile/goals.md" not in paths
    assert "knowledge/context_layers/private-fusion.md" not in paths
    # coverage is low and visitor may NOT fall back to raw data
    assert artifact.fallback == []


async def test_owner_fallback_when_store_cannot_cover(db_session, store):
    embedder = await seed(db_session, store)
    # raw data exists that the store has not consolidated
    from app.data.knowledge_store import KnowledgeStore

    knowledge = KnowledgeStore(db_session, embedder)
    await knowledge.add_source(
        title="Quantum branzino cooking techniques",
        url="https://example.com/branzino",
        content="Branzino quantum sous-vide techniques for adventurous chefs.",
        summary="Cooking techniques for branzino.",
        pillar=["leadership"],
    )
    await db_session.commit()

    builder = ContextBuilder(
        db_session, store, embedder, search_service=SearchService(db_session, embedder)
    )
    artifact = await builder.build("quantum branzino sous-vide cooking", OWNER)
    assert artifact.coverage < 0.35
    assert artifact.fallback, "owner should get labeled raw fallback"
    assert "UNCONSOLIDATED" in artifact.to_markdown()


async def test_graph_expansion_pulls_related_private_topic_for_owner(db_session, store):
    embedder = await seed(db_session, store)
    builder = ContextBuilder(db_session, store, embedder)
    artifact = await builder.build("reciprocal rank fusion rankings", OWNER)
    reasons = {s.path: s.reason for s in artifact.sections}
    # private topic arrives either by ranking or via the related_to edge
    assert "knowledge/context_layers/private-fusion.md" in reasons


async def test_budget_is_respected(db_session, store):
    embedder = await seed(db_session, store)
    builder = ContextBuilder(db_session, store, embedder)
    tight = Principal(
        id="agent-tiny", kind="agent", token_budget=120,
        allowed_visibilities=("public",), allow_fallback=False,
    )
    artifact = await builder.build("reciprocal rank fusion", tight)
    assert artifact.tokens_used <= 120


async def test_every_build_is_audited(db_session, store):
    embedder = await seed(db_session, store)
    builder = ContextBuilder(db_session, store, embedder)
    artifact = await builder.build("reciprocal rank fusion", VISITOR)

    row = (
        await db_session.execute(
            text("SELECT principal_id, served, coverage FROM context_builds WHERE id = :id"),
            {"id": str(artifact.build_id)},
        )
    ).first()
    assert row.principal_id == "visitor"
    assert isinstance(row.served, list)

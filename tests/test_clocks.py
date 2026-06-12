"""Consolidation clock tests with deterministic fakes."""

import uuid

import pytest
from sqlalchemy import text

from app.context.consolidation.deep import DeepClock
from app.context.consolidation.light import LightClock
from app.context.consolidation.rem import RemClock
from app.context.review import ReviewService
from app.data.knowledge_store import KnowledgeStore
from app.data.lineage import LineageService, TrackedLLMProvider
from tests.fakes import FakeLLM, HashingEmbedder


def tracked(db, fake_llm):
    return TrackedLLMProvider(fake_llm, LineageService(db))


@pytest.fixture
def embedder():
    return HashingEmbedder()


async def add_source(db, embedder, trust_tier, title="Context rot study"):
    knowledge_store = KnowledgeStore(db, embedder)
    item = await knowledge_store.add_source(
        title=title,
        url=f"https://example.com/{uuid.uuid4()}",
        content="Long context degrades attention non-uniformly even on simple tasks.",
        summary="Study of context window degradation.",
        pillar=["context_layers"],
        trust_tier=trust_tier,
    )
    await db.commit()
    return item


LIGHT_DECISION = {
    "action": "new_topic",
    "topic_path": "",
    "new_topic": {
        "slug": "context-rot",
        "title": "Context Rot",
        "pillar": "context_layers",
        "gist": "Long context degrades model attention.",
    },
    "claims": ["LLM performance degrades non-uniformly with context length"],
}


async def test_light_clock_untrusted_goes_to_review_branch(db_session, store, embedder):
    source = await add_source(db_session, embedder, "untrusted")
    clock = LightClock(db_session, store, tracked(db_session, FakeLLM(LIGHT_DECISION)), embedder)
    result = await clock.run([source.id])

    assert result["branch"].startswith("consolidation/")
    assert result["files_changed"] == ["knowledge/context_layers/context-rot.md"]
    # not on main yet, and the source is NOT consolidated until approval
    assert await store.read("knowledge/context_layers/context-rot.md") is None
    flag = (
        await db_session.execute(
            text("SELECT is_consolidated FROM source_content WHERE id = :id"),
            {"id": str(source.id)},
        )
    ).scalar()
    assert flag is False


async def test_light_clock_owner_tier_commits_to_main(db_session, store, embedder):
    source = await add_source(db_session, embedder, "owner")
    clock = LightClock(db_session, store, tracked(db_session, FakeLLM(LIGHT_DECISION)), embedder)
    result = await clock.run([source.id])

    assert result["branch"] is None
    content = await store.read("knowledge/context_layers/context-rot.md")
    assert "Context Rot" in content
    assert f"[source:{source.id}]" in content
    # indexed + edged immediately
    row = (
        await db_session.execute(
            text("SELECT kind FROM context_sections WHERE path = 'knowledge/context_layers/context-rot.md'")
        )
    ).scalar()
    assert row == "topic"
    edge = (
        await db_session.execute(
            text("SELECT object_ref FROM context_edges WHERE predicate = 'derived_from'")
        )
    ).scalar()
    assert edge == f"source:{source.id}"


async def test_review_approve_merges_and_marks_consolidated(db_session, store, embedder):
    source = await add_source(db_session, embedder, "untrusted")
    clock = LightClock(db_session, store, tracked(db_session, FakeLLM(LIGHT_DECISION)), embedder)
    result = await clock.run([source.id])
    branch = result["branch"]

    review = ReviewService(db_session, store, embedder)
    pending = await review.pending()
    assert [p["branch"] for p in pending] == [branch]
    assert "+# Context Rot" in pending[0]["diff"]

    outcome = await review.approve(branch)
    assert outcome["sources_consolidated"] == 1
    assert "Context Rot" in await store.read("knowledge/context_layers/context-rot.md")
    flag = (
        await db_session.execute(
            text("SELECT is_consolidated FROM source_content WHERE id = :id"),
            {"id": str(source.id)},
        )
    ).scalar()
    assert flag is True


async def test_review_reject_closes_sources(db_session, store, embedder):
    source = await add_source(db_session, embedder, "untrusted")
    clock = LightClock(db_session, store, tracked(db_session, FakeLLM(LIGHT_DECISION)), embedder)
    result = await clock.run([source.id])

    review = ReviewService(db_session, store, embedder)
    outcome = await review.reject(result["branch"])
    assert outcome["sources_closed"] == 1
    assert await store.read("knowledge/context_layers/context-rot.md") is None
    # closed sources do not loop back through the clock
    rerun = await LightClock(
        db_session, store, tracked(db_session, FakeLLM(LIGHT_DECISION)), embedder
    ).run([source.id])
    assert rerun["processed"] == 0


async def test_rem_clock_regenerates_gist_and_index(db_session, store, embedder):
    # owner-tier consolidation puts a topic on main first
    source = await add_source(db_session, embedder, "owner")
    await LightClock(db_session, store, tracked(db_session, FakeLLM(LIGHT_DECISION)), embedder).run(
        [source.id]
    )

    rem_llm = FakeLLM({"gist": "A sharper consolidated gist.", "contradictions": []})
    rem = RemClock(db_session, store, tracked(db_session, rem_llm), embedder)
    result = await rem.run()

    assert "knowledge/context_layers/context-rot.md" in result["files_changed"]
    content = await store.read("knowledge/context_layers/context-rot.md")
    assert "A sharper consolidated gist." in content
    index_md = await store.read("INDEX.md")
    assert "context-rot.md" in index_md


async def test_deep_clock_drafts_skill_on_review_branch(db_session, store, embedder):
    knowledge_store = KnowledgeStore(db_session, embedder)
    await knowledge_store.add_artifact(
        title="Context build review checklist",
        content="1. Check citations. 2. Check budget. 3. Check freshness.",
        pillar=["context_layers"],
    )
    await db_session.commit()

    deep_llm = FakeLLM(
        {
            "entities": [],
            "slug": "context-build-review",
            "title": "Context Build Review",
            "trigger_description": "before approving any consolidation branch",
            "steps": ["Check citations", "Check budget", "Check freshness"],
            "failure_modes": ["Rubber-stamping diffs"],
            "derived_from": [],
        }
    )
    deep = DeepClock(db_session, store, tracked(db_session, deep_llm), embedder)
    result = await deep.run()

    assert result["skill_draft"] == "skills/context-build-review/SKILL.md"
    # draft is on a review branch, not main
    assert await store.read("skills/context-build-review/SKILL.md") is None
    branches = await store.list_review_branches()
    assert any(b.endswith("-skills") for b in branches)

    review = ReviewService(db_session, store, embedder)
    await review.approve(branches[0])
    content = await store.read("skills/context-build-review/SKILL.md")
    assert "maturity: draft" in content
    assert "Check citations" in content
    # approved skill is indexed as kind=skill
    kind = (
        await db_session.execute(
            text("SELECT kind FROM context_sections WHERE path = 'skills/context-build-review/SKILL.md'")
        )
    ).scalar()
    assert kind == "skill"


async def test_clock_failure_records_run_and_alerts(db_session, store, embedder, monkeypatch):
    alerts = []

    async def capture_alert(message):
        alerts.append(message)

    monkeypatch.setattr("app.context.consolidation.base.send_alert", capture_alert)

    class ExplodingLLM(FakeLLM):
        async def complete_structured(self, *args, **kwargs):
            raise RuntimeError("provider down")

    source = await add_source(db_session, embedder, "untrusted")
    clock = LightClock(db_session, store, tracked(db_session, ExplodingLLM()), embedder)
    with pytest.raises(RuntimeError):
        await clock.run([source.id])

    status = (
        await db_session.execute(
            text("SELECT status, error FROM consolidation_runs ORDER BY started_at DESC")
        )
    ).first()
    assert status.status == "failed"
    assert "provider down" in status.error
    assert alerts and "light" in alerts[0]

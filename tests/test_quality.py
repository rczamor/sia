"""Quality tests: context_score on every build, regression runner, citation ledger,
health endpoint."""

from sqlalchemy import text

from app.context.builder import ContextBuilder
from app.context.quality import run_regression, score_artifact
from tests.test_builder import OWNER, seed

REGRESSION_FIXTURE = """goal: "reciprocal rank fusion rankings"
expect_paths:
  - knowledge/context_layers/rrf-fusion.md
min_coverage: 0.2
"""

FAILING_FIXTURE = """goal: "completely unrelated quantum gastronomy"
expect_paths:
  - knowledge/context_layers/nonexistent.md
min_coverage: 0.9
"""


async def test_every_build_gets_a_context_score(db_session, store):
    embedder = await seed(db_session, store)
    builder = ContextBuilder(db_session, store, embedder)
    artifact = await builder.build("reciprocal rank fusion rankings", OWNER)
    score = await score_artifact(db_session, artifact)

    assert 0 < score.composite <= 1
    assert score.grounding == 1.0  # both served topics carry citations
    assert score.consolidation == 1.0  # no fallback tokens

    row = (
        await db_session.execute(
            text("SELECT context_score, flags FROM context_builds WHERE id = :id"),
            {"id": str(artifact.build_id)},
        )
    ).first()
    assert row.context_score is not None
    assert row.flags["score_components"]["coverage"] > 0


async def test_regression_runner_passes_and_fails_correctly(db_session, store):
    embedder = await seed(db_session, store)
    await store.commit(
        {
            ".sia/regression/rrf.yaml": REGRESSION_FIXTURE,
            ".sia/regression/failing.yaml": FAILING_FIXTURE,
        },
        "add regression fixtures",
    )
    builder = ContextBuilder(db_session, store, embedder)
    results = await run_regression(db_session, store, builder)

    by_fixture = {r.fixture: r for r in results}
    assert by_fixture[".sia/regression/rrf.yaml"].passed
    failing = by_fixture[".sia/regression/failing.yaml"]
    assert not failing.passed
    assert "knowledge/context_layers/nonexistent.md" in failing.missing_paths


async def test_citation_ledger_adjusts_priorities(db_session, store):
    from app.context.consolidation.rem import RemClock
    from app.data.lineage import LineageService, TrackedLLMProvider
    from tests.fakes import FakeLLM

    embedder = await seed(db_session, store)
    builder = ContextBuilder(db_session, store, embedder)
    artifact = await builder.build("reciprocal rank fusion rankings", OWNER)

    # flag the build useful
    build_row = (
        await db_session.execute(
            text("SELECT id FROM context_builds WHERE id = :id"), {"id": str(artifact.build_id)}
        )
    ).scalar()
    await db_session.execute(
        text("UPDATE context_builds SET flags = '{\"useful\": true}' WHERE id = :id"),
        {"id": str(build_row)},
    )
    await db_session.commit()

    before = _priority_of(await store.read("knowledge/context_layers/rrf-fusion.md"))

    rem = RemClock(
        db_session, store,
        TrackedLLMProvider(FakeLLM({"gist": "", "contradictions": []}), LineageService(db_session)),
        embedder,
    )
    result = await rem.run()
    assert result["priority_adjustments"] >= 1

    after = _priority_of(await store.read("knowledge/context_layers/rrf-fusion.md"))
    assert after > before

    # ledger is applied once — a second REM run does not double-count
    rem_two = RemClock(
        db_session, store,
        TrackedLLMProvider(FakeLLM({"gist": "", "contradictions": []}), LineageService(db_session)),
        embedder,
    )
    result_two = await rem_two.run()
    assert result_two["priority_adjustments"] == 0


def _priority_of(content: str) -> float:
    from app.context.store.documents import MarkdownSerializer

    return float(MarkdownSerializer().loads("x.md", content).front.get("priority", 0.5))


async def test_health_endpoint_reports_metrics(client, db_session, store):
    embedder = await seed(db_session, store)
    builder = ContextBuilder(db_session, store, embedder)
    artifact = await builder.build("reciprocal rank fusion", OWNER)
    await score_artifact(db_session, artifact)

    response = await client.get("/api/context/health")
    assert response.status_code == 200
    health = response.json()
    assert health["builds"]["last_7d"] >= 1
    assert health["builds"]["avg_context_score_7d"] > 0
    assert isinstance(health["consolidation"], list)
    assert any(s["kind"] == "topic" for s in health["store"])


async def test_health_dashboard_renders(client, db_session, store):
    response = await client.get("/admin/health")
    assert response.status_code == 200
    assert "Context Health" in response.text


async def test_graph_endpoint_carries_overlay_data(client, db_session, store):
    embedder = await seed(db_session, store)
    builder = ContextBuilder(db_session, store, embedder)
    await builder.build("reciprocal rank fusion rankings", OWNER)

    response = await client.get("/api/context/graph")
    nodes = response.json()["nodes"]
    topic = next(n for n in nodes if n["id"].endswith("rrf-fusion.md"))
    assert "age_days" in topic
    assert topic["uses_30d"] >= 1  # served by the build above

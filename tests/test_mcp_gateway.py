"""MCP gateway tests: mount auth and tool behavior (tools called directly with the
principal contextvar set, as the auth middleware does)."""

import pytest

from app.gateway import mcp as gateway
from tests.test_builder import OWNER, VISITOR, seed


@pytest.fixture
def as_owner():
    token = gateway.current_principal.set(OWNER)
    yield
    gateway.current_principal.reset(token)


@pytest.fixture
def as_visitor():
    token = gateway.current_principal.set(VISITOR)
    yield
    gateway.current_principal.reset(token)


async def test_mcp_mount_requires_key(anon_client):
    response = await anon_client.post("/mcp/", json={})
    assert response.status_code == 401
    response = await anon_client.post(
        "/mcp/", json={}, headers={"Authorization": "Bearer sia_invalid"}
    )
    assert response.status_code == 401


async def test_tools_require_principal():
    gateway.current_principal.set(None)
    with pytest.raises(PermissionError):
        await gateway.sia_list_topics()


async def test_build_context_tool_returns_artifact(db_session, store, as_owner, fake_runtime):
    await seed(db_session, store)
    result = await gateway.sia_build_context(goal="reciprocal rank fusion")
    assert "# Context for: reciprocal rank fusion" in result
    assert "build_id:" in result


async def test_list_and_read_respect_visibility(db_session, store, as_visitor, monkeypatch):
    await seed(db_session, store)

    class FakeRuntime:
        context_store = store

    async def fake_get_runtime():
        return FakeRuntime()

    monkeypatch.setattr("app.runtime.get_runtime", fake_get_runtime)

    topics = await gateway.sia_list_topics()
    paths = [t["path"] for t in topics]
    assert "knowledge/context_layers/rrf-fusion.md" in paths
    assert "knowledge/context_layers/private-fusion.md" not in paths

    content = await gateway.sia_read_topic("knowledge/context_layers/rrf-fusion.md")
    assert "RRF Fusion" in content

    with pytest.raises(PermissionError):
        await gateway.sia_read_topic("knowledge/context_layers/private-fusion.md")


async def test_read_topic_blocks_path_traversal(as_owner):
    with pytest.raises(ValueError):
        await gateway.sia_read_topic("knowledge/../.sia/lock")
    with pytest.raises(ValueError):
        await gateway.sia_read_topic("/etc/passwd")


async def test_visitor_cannot_write(as_visitor):
    with pytest.raises(PermissionError):
        await gateway.sia_add_thought(content="visitor graffiti")
    with pytest.raises(PermissionError):
        await gateway.sia_add_source(url="https://example.com/x")


async def test_consolidate_is_owner_only(as_visitor):
    with pytest.raises(PermissionError):
        await gateway.sia_consolidate("light")


async def test_flag_updates_build(db_session, store, as_owner):
    embedder = await seed(db_session, store)
    from app.context.builder import ContextBuilder

    builder = ContextBuilder(db_session, store, embedder)
    artifact = await builder.build("reciprocal rank fusion", OWNER)

    result = await gateway.sia_flag(str(artifact.build_id), useful=True, note="used both claims")
    assert result["useful"] is True

    from sqlalchemy import text

    flags = (
        await db_session.execute(
            text("SELECT flags FROM context_builds WHERE id = :id"),
            {"id": str(artifact.build_id)},
        )
    ).scalar()
    assert flags["useful"] is True

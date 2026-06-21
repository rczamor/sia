"""Context store tests: serialization, git backend, trust-gated branches, review."""

from app.context.store.documents import MarkdownSerializer, StoreDocument


def test_markdown_serializer_roundtrip():
    serializer = MarkdownSerializer()
    document = StoreDocument(
        path="knowledge/context_layers/rrf.md",
        front={"id": "topic-rrf", "pillar": "context_layers", "priority": 0.7,
               "sources": ["abc"], "related": ["other-topic"]},
        body="# RRF\n\n## Gist\n\nFusion of rankings.\n\n## Key claims\n\n- claim one [source:abc]\n",
    )
    text = serializer.dumps(document)
    parsed = serializer.loads(document.path, text)
    assert parsed.front == document.front
    assert parsed.section("Gist") == "Fusion of rankings."
    assert "claim one" in parsed.section("Key claims")
    assert parsed.kind == "topic"


def test_document_without_front_matter():
    serializer = MarkdownSerializer()
    parsed = serializer.loads("knowledge/x/y.md", "# Title\n\nBody only.")
    assert parsed.front == {}
    assert parsed.body.startswith("# Title")


async def test_scaffold_creates_layout(store):
    paths = await store.list_paths()
    assert "INDEX.md" in paths
    assert "profile/identity.md" in paths
    assert ".sia/store-spec.md" in paths
    assert ".sia/skills-spec.md" in paths
    # scaffold is idempotent
    from app.context.store.layout import scaffold_store

    sha_before = await store.head_sha()
    await scaffold_store(store)
    assert await store.head_sha() == sha_before


async def test_commit_to_main_and_read(store):
    sha = await store.commit({"knowledge/context_layers/test.md": "# Test\n"}, "add topic")
    assert len(sha) == 40
    assert await store.read("knowledge/context_layers/test.md") == "# Test\n"


async def test_branch_commit_does_not_touch_main(store):
    await store.commit(
        {"knowledge/context_layers/pending.md": "# Pending\n"},
        "light: consolidate",
        branch="consolidation/2026-06-12",
    )
    # main does not see the file
    assert await store.read("knowledge/context_layers/pending.md") is None
    branches = await store.list_review_branches()
    assert branches == ["consolidation/2026-06-12"]
    diff = await store.diff("consolidation/2026-06-12")
    assert "+# Pending" in diff


async def test_commit_rejects_path_traversal(store):
    """LLM-derived slugs/pillars must never escape the store root (CWE-22)."""
    import pytest

    from app.context.store.gitstore import StoreError

    for bad in (
        "../../../../tmp/pwn.md", "/etc/cron.d/x", "knowledge/../../escape.md",
        ".git/hooks/post-commit", "knowledge/../.git/config",
    ):
        with pytest.raises(StoreError):
            await store.commit({bad: "owned"}, "attempt traversal")
    # the escape target was never written
    import os

    assert not os.path.exists("/tmp/pwn.md")


async def test_safe_slug_and_pillar_sanitize_llm_paths():
    from app.context.consolidation.light import new_topic_document, safe_pillar
    from app.context.store.documents import safe_slug
    import uuid

    assert safe_slug("../../etc/passwd") == "etc-passwd"
    assert safe_slug("../..") == "untitled"
    assert safe_pillar("../../evil") == "context_layers"
    assert safe_pillar("context_layers") == "context_layers"

    doc = new_topic_document(
        slug="../../../../tmp/x", title="T", pillar="../../evil",
        gist="g", claims=["c"], source_id=uuid.uuid4(),
    )
    assert ".." not in doc.path
    assert doc.path.startswith("knowledge/context_layers/")


async def test_merge_conflict_aborts_and_leaves_clean_tree(store):
    """A conflicting review merge must not leave the store in a half-merged state."""
    import pytest

    from app.context.store.gitstore import StoreError

    # main and the branch both edit the same file differently → conflict on merge
    await store.commit({"knowledge/context_layers/c.md": "# main version\n"}, "main edit")
    await store.commit(
        {"knowledge/context_layers/c.md": "# branch version\n"},
        "branch edit",
        branch="consolidation/2026-06-12",
    )
    await store.commit({"knowledge/context_layers/c.md": "# main moved on\n"}, "main moves")

    with pytest.raises(StoreError):
        await store.merge_branch("consolidation/2026-06-12")

    # store is usable afterward: no conflict markers, reads/commits still work
    content = await store.read("knowledge/context_layers/c.md")
    assert "<<<<<<<" not in content
    sha = await store.commit({"knowledge/context_layers/d.md": "# ok\n"}, "post-conflict commit")
    assert len(sha) == 40


async def test_merge_review_branch(store):
    await store.commit(
        {"knowledge/context_layers/approved.md": "# Approved\n"},
        "light: consolidate",
        branch="consolidation/2026-06-12",
    )
    await store.merge_branch("consolidation/2026-06-12")
    assert await store.read("knowledge/context_layers/approved.md") == "# Approved\n"
    assert await store.list_review_branches() == []


async def test_delete_is_archive_only_by_convention(store):
    # the API supports deletion for INDEX regeneration; pruning uses status flips —
    # verify a status flip keeps the file present in history
    await store.commit({"knowledge/context_layers/old.md": "---\nstatus: active\n---\n\n# Old\n"}, "add")
    await store.commit({"knowledge/context_layers/old.md": "---\nstatus: stale\n---\n\n# Old\n"}, "prune")
    content = await store.read("knowledge/context_layers/old.md")
    assert "status: stale" in content


def test_legacy_consolidation_backfill_document_shape():
    import uuid
    from datetime import datetime, timezone

    from scripts.backfill_consolidations import document_for_legacy_consolidation

    source_id = uuid.uuid4()
    thought_id = uuid.uuid4()
    document = document_for_legacy_consolidation(
        {
            "id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
            "insight_text": "Context must be synthesized before inference.",
            "connected_source_ids": [source_id],
            "connected_thought_ids": [thought_id],
            "pillar": ["context_layers"],
            "confidence": 0.7,
            "created_at": datetime(2026, 6, 12, tzinfo=timezone.utc),
        }
    )

    assert document.path.startswith("knowledge/context_layers/")
    assert document.front["legacy_consolidation_id"] == "11111111-1111-1111-1111-111111111111"
    assert str(source_id) in document.front["sources"]
    assert f"[thought:{thought_id}]" in document.body


async def test_commit_async_gate_serializes_before_thread_pool(store, monkeypatch):
    import asyncio
    import threading
    import time

    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_commit_sync(files, message, branch):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return "a" * 40

    monkeypatch.setattr(store, "_commit_sync", fake_commit_sync)

    await asyncio.gather(
        store.commit({"knowledge/context_layers/a.md": "# A\n"}, "a"),
        store.commit({"knowledge/context_layers/b.md": "# B\n"}, "b"),
    )

    assert max_active == 1

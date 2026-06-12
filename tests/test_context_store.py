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

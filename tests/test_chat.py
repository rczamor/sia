"""Chat endpoint tests: ContextBuilder grounding and principal boundaries."""

from app.context.index import StoreIndexer
from app.models.enums import PluginCategory
from app.plugins.base import PluginHealth
from tests.fakes import FakeLLM, HashingEmbedder

PUBLIC_TOPIC = """---
id: topic-public-rrf
pillar: context_layers
priority: 0.9
visibility: public
freshness: 2026-06-10
---

# Public RRF

## Gist

Reciprocal rank fusion combines keyword and vector rankings.

## Key claims

- RRF helps merge heterogeneous retrievers.
"""

PRIVATE_TOPIC = """---
id: topic-private-rrf
pillar: context_layers
priority: 1.0
visibility: private
freshness: 2026-06-10
---

# Private RRF

## Gist

Private notes about unreleased ranking experiments.
"""


class FakeLLMPlugin:
    plugin_id = "fake-llm"
    category = PluginCategory.LLM

    def __init__(self, provider):
        self.provider = provider

    async def initialize(self, config):
        pass

    async def health_check(self):
        return PluginHealth(healthy=True)

    async def shutdown(self):
        pass


async def _seed_chat_store(db, store):
    await store.commit(
        {
            "knowledge/context_layers/public-rrf.md": PUBLIC_TOPIC,
            "knowledge/context_layers/private-rrf.md": PRIVATE_TOPIC,
        },
        "seed chat topics",
    )
    await StoreIndexer(db, store, HashingEmbedder()).sync()


async def test_anonymous_chat_uses_visitor_public_context(
    anon_client, db_session, store, fake_runtime
):
    fake_llm = FakeLLM()
    fake_runtime.plugins.register(FakeLLMPlugin(fake_llm))
    await _seed_chat_store(db_session, store)

    response = await anon_client.post(
        "/api/chat", json={"question": "How should I use reciprocal rank fusion?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["principal"] == "visitor"
    assert body["answer"] == "fake completion"
    paths = [source["path"] for source in body["sources"]]
    assert "knowledge/context_layers/public-rrf.md" in paths
    assert "knowledge/context_layers/private-rrf.md" not in paths
    assert "Context for:" in fake_llm.calls[0]["messages"][0]["content"]


async def test_owner_chat_can_use_private_context(client, db_session, store, fake_runtime):
    fake_llm = FakeLLM()
    fake_runtime.plugins.register(FakeLLMPlugin(fake_llm))
    await _seed_chat_store(db_session, store)

    response = await client.post(
        "/api/chat", json={"question": "How should I use reciprocal rank fusion?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["principal"] == "owner"
    paths = [source["path"] for source in body["sources"]]
    assert "knowledge/context_layers/private-rrf.md" in paths

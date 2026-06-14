# Writing a Sia plugin

Sia discovers plugins through the `sia.plugins` entry-point group. A plugin is a
class with identity, an async lifecycle, and a `provider` implementing the protocol
for its category. Ship one in any pip package — no core changes.

## Categories and provider protocols

| Category (`PluginCategory`) | Provider protocol (`app.providers.base`) | Bundled examples |
|---|---|---|
| `llm` | `LLMProvider` (`complete`, `complete_structured`) | anthropic, openrouter |
| `embeddings` | `EmbeddingProvider` (`embed`, `embed_batch`, `dimensions`) | ollama |
| `llmops` | `LLMOpsProvider` (`trace`, `get_prompt`, `score`) | langfuse |
| `ingestion` | `IngestionSource` (`fetch_new_items`) | feedly, gdocs |
| `store_backend` | `ContextStoreBackend` (`app.context.store.gitstore`) | local git |

## Minimal example

```python
# my_package/plugin.py
from app.models.enums import PluginCategory
from app.plugins.base import PluginHealth, PluginInitError

class MyLLMPlugin:
    plugin_id = "my-llm"
    category = PluginCategory.LLM

    def __init__(self):
        self._provider = None

    @property
    def provider(self):
        if self._provider is None:
            raise RuntimeError("Plugin not initialized")
        return self._provider

    async def initialize(self, config: dict) -> None:
        import os
        key = os.environ.get("MY_LLM_API_KEY")
        if not key:
            raise PluginInitError("MY_LLM_API_KEY is not set")  # logged + skipped
        self._provider = MyProvider(key, model=config.get("default_model"))

    async def health_check(self) -> PluginHealth:
        return PluginHealth(healthy=self._provider is not None)

    async def shutdown(self) -> None:
        self._provider = None
```

```toml
# my_package/pyproject.toml
[project.entry-points."sia.plugins"]
my-llm = "my_package.plugin:MyLLMPlugin"
```

## Activation

```sql
INSERT INTO plugins (id, display_name, category, enabled)
VALUES ('my-llm', 'My LLM', 'llm', true);
```

Then point an operation at it in `ai_config`:
`llm_consolidation = {"provider": "my-llm", "model": "..."}`.

## Rules

- **Secrets from the environment only.** `config` (from the plugins table) is for
  non-secret tuning. Raising `PluginInitError` on missing credentials makes the
  system degrade gracefully instead of failing boot.
- Providers must be safe for concurrent use from multiple requests.
- LLM providers are used for Sia's *internal* context operations (classification,
  consolidation, synthesis). Sia core never generates end-user content.
- **Ingestion sources with public URLs** (e.g. `feedly`) can enqueue
  `ingest_url_task` per item and let the SSRF-guarded fetcher re-fetch. **Sources
  whose content is auth-gated** (e.g. `gdocs`, where the export URL needs a
  bearer token) should pass the already-fetched text to `ingest_content_task`
  instead — see `app/plugins/ingestion/gdocs.py` and the `gdocs_poll` task.
  Absorbing a source this way makes it reachable in any harness only through
  `sia_build_context`; see [default-context-source.md](default-context-source.md).

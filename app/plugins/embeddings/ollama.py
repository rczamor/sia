from typing import Any

import httpx

from app.config import settings
from app.models.enums import PluginCategory
from app.plugins.base import PluginHealth
from app.providers.embeddings.ollama import OllamaEmbedding


class OllamaEmbeddingsPlugin:
    plugin_id = "ollama"
    category = PluginCategory.EMBEDDINGS

    def __init__(self):
        self._provider: OllamaEmbedding | None = None

    @property
    def provider(self) -> OllamaEmbedding:
        if self._provider is None:
            raise RuntimeError("Plugin not initialized")
        return self._provider

    async def initialize(self, config: dict[str, Any]) -> None:
        self._provider = OllamaEmbedding(
            model=config.get("model", "nomic-embed-text"),
            base_url=settings.ollama_url,
        )

    async def health_check(self) -> PluginHealth:
        if self._provider is None:
            return PluginHealth(healthy=False, message="not initialized")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{settings.ollama_url}/api/tags")
                response.raise_for_status()
            return PluginHealth(healthy=True)
        except httpx.HTTPError as exc:
            return PluginHealth(healthy=False, message=f"Ollama unreachable: {exc}")

    async def shutdown(self) -> None:
        self._provider = None

from typing import Any

from app.config import settings
from app.models.enums import PluginCategory
from app.plugins.base import PluginHealth, PluginInitError
from app.providers.llm.anthropic import AnthropicProvider


class AnthropicLLMPlugin:
    plugin_id = "anthropic"
    category = PluginCategory.LLM

    def __init__(self):
        self._provider: AnthropicProvider | None = None

    @property
    def provider(self) -> AnthropicProvider:
        if self._provider is None:
            raise RuntimeError("Plugin not initialized")
        return self._provider

    async def initialize(self, config: dict[str, Any]) -> None:
        if not settings.anthropic_api_key:
            raise PluginInitError("ANTHROPIC_API_KEY is not set")
        self._provider = AnthropicProvider(api_key=settings.anthropic_api_key)

    async def health_check(self) -> PluginHealth:
        return PluginHealth(healthy=self._provider is not None)

    async def shutdown(self) -> None:
        self._provider = None

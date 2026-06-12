from typing import Any

from app.config import settings
from app.models.enums import PluginCategory
from app.plugins.base import PluginHealth, PluginInitError
from app.providers.llm.openrouter import DEFAULT_BASE_URL, DEFAULT_MODEL, OpenRouterProvider


class OpenRouterLLMPlugin:
    plugin_id = "openrouter"
    category = PluginCategory.LLM

    def __init__(self):
        self._provider: OpenRouterProvider | None = None

    @property
    def provider(self) -> OpenRouterProvider:
        if self._provider is None:
            raise RuntimeError("Plugin not initialized")
        return self._provider

    async def initialize(self, config: dict[str, Any]) -> None:
        if not settings.openrouter_api_key:
            raise PluginInitError("OPENROUTER_API_KEY is not set")
        self._provider = OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            base_url=config.get("base_url", settings.openrouter_base_url or DEFAULT_BASE_URL),
            default_model=config.get("default_model", DEFAULT_MODEL),
        )

    async def health_check(self) -> PluginHealth:
        return PluginHealth(healthy=self._provider is not None)

    async def shutdown(self) -> None:
        self._provider = None

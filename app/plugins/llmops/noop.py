from typing import Any

from app.models.enums import PluginCategory
from app.plugins.base import PluginHealth


class NoOpLLMOps:
    """Passthrough LLM ops provider — no tracing, no prompt management.
    Used in Phase 1 before Langfuse is configured."""

    @property
    def plugin_id(self) -> str:
        return "noop"

    @property
    def category(self) -> PluginCategory:
        return PluginCategory.LLMOPS

    async def initialize(self, config: dict[str, Any]) -> None:
        pass

    async def health_check(self) -> PluginHealth:
        return PluginHealth(healthy=True, message="NoOp — tracing disabled")

    async def shutdown(self) -> None:
        pass

    async def trace(
        self,
        name: str,
        input_data: dict | None = None,
        output_data: dict | None = None,
        metadata: dict | None = None,
    ) -> str | None:
        return None

    async def get_prompt(self, name: str, label: str = "production") -> str | None:
        return None

    async def score(
        self, trace_id: str, name: str, value: float, comment: str | None = None
    ) -> None:
        pass

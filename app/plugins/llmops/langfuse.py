"""Langfuse LLM-ops plugin: tracing, scoring, and prompt management.

The Langfuse SDK is synchronous; calls are pushed to a thread so the event loop is
never blocked. If credentials are missing the plugin refuses to initialize and the
runtime falls back to the NoOp provider.
"""

import asyncio
import logging
from typing import Any

from app.config import settings
from app.models.enums import PluginCategory
from app.plugins.base import PluginHealth, PluginInitError

logger = logging.getLogger(__name__)


class LangfuseLLMOps:
    """Implements the LLMOpsProvider protocol backed by Langfuse."""

    def __init__(self, client):
        self._client = client

    async def trace(
        self,
        name: str,
        input_data: dict | None = None,
        output_data: dict | None = None,
        metadata: dict | None = None,
    ) -> str | None:
        def _trace():
            trace = self._client.trace(
                name=name, input=input_data, output=output_data, metadata=metadata
            )
            return trace.id

        try:
            return await asyncio.to_thread(_trace)
        except Exception:
            logger.exception("Langfuse trace failed")
            return None

    async def get_prompt(self, name: str, label: str = "production") -> str | None:
        def _get():
            return self._client.get_prompt(name, label=label).prompt

        try:
            return await asyncio.to_thread(_get)
        except Exception:
            # Missing prompt is not an error — callers fall back to local constants.
            return None

    async def score(
        self, trace_id: str, name: str, value: float, comment: str | None = None
    ) -> None:
        def _score():
            self._client.score(trace_id=trace_id, name=name, value=value, comment=comment)

        try:
            await asyncio.to_thread(_score)
        except Exception:
            logger.exception("Langfuse score failed")


class LangfusePlugin:
    plugin_id = "langfuse"
    category = PluginCategory.LLMOPS

    def __init__(self):
        self._provider: LangfuseLLMOps | None = None
        self._client = None

    @property
    def provider(self) -> LangfuseLLMOps:
        if self._provider is None:
            raise RuntimeError("Plugin not initialized")
        return self._provider

    async def initialize(self, config: dict[str, Any]) -> None:
        if not (settings.langfuse_public_key and settings.langfuse_secret_key):
            raise PluginInitError("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set")
        from langfuse import Langfuse

        self._client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host or "https://cloud.langfuse.com",
        )
        self._provider = LangfuseLLMOps(self._client)

    async def health_check(self) -> PluginHealth:
        if self._client is None:
            return PluginHealth(healthy=False, message="not initialized")
        try:
            ok = await asyncio.to_thread(self._client.auth_check)
            return PluginHealth(healthy=bool(ok))
        except Exception as exc:
            return PluginHealth(healthy=False, message=str(exc))

    async def shutdown(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.flush)
        self._provider = None
        self._client = None

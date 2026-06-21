import logging
import time
import uuid
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import ProcessLineage
from app.providers.base import LLMOpsProvider, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class LineageService:
    """Records process lineage for every LLM operation."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(
        self,
        operation_type: str,
        input_content_ids: list[uuid.UUID] | None = None,
        input_context_summary: str | None = None,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
        model: str | None = None,
        model_params: dict | None = None,
        output_entity_type: str | None = None,
        output_entity_id: uuid.UUID | None = None,
        output_summary: str | None = None,
        quality_score: float | None = None,
        duration_ms: int | None = None,
        token_count_input: int | None = None,
        token_count_output: int | None = None,
        cost_usd: float | None = None,
        langfuse_trace_id: str | None = None,
    ) -> uuid.UUID:
        lineage_id = uuid.uuid4()
        stmt = insert(ProcessLineage).values(
            id=lineage_id,
            langfuse_trace_id=langfuse_trace_id,
            operation_type=operation_type,
            input_content_ids=input_content_ids or [],
            input_context_summary=input_context_summary,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            model=model,
            model_params=model_params,
            output_entity_type=output_entity_type,
            output_entity_id=output_entity_id,
            output_summary=output_summary,
            quality_score=quality_score,
            duration_ms=duration_ms,
            token_count_input=token_count_input,
            token_count_output=token_count_output,
            cost_usd=cost_usd,
        )
        await self.db.execute(stmt)
        await self.db.flush()
        return lineage_id


class TrackedLLMProvider:
    """Wraps an LLM provider to automatically capture process lineage and emit
    one observability trace per call when an LLM-ops provider is configured."""

    def __init__(
        self,
        provider: LLMProvider,
        lineage: LineageService,
        llmops: LLMOpsProvider | None = None,
    ):
        self._provider = provider
        self._lineage = lineage
        self._llmops = llmops

    async def prompt(
        self, name: str, fallback: str, label: str = "production"
    ) -> str:
        """Load a managed prompt when LLM-ops supports prompt management.

        Langfuse outages or missing prompt names should never break the context
        engine; callers fall back to the local prompt constant and still record
        lineage with the same prompt name.
        """
        if self._llmops is None:
            return fallback
        try:
            managed = await self._llmops.get_prompt(name, label=label)
        except Exception:
            logger.exception("Managed prompt lookup failed for %s", name)
            return fallback
        return managed or fallback

    async def _trace(
        self, operation_type: str, prompt_name: str | None, messages, output_summary: str
    ) -> str | None:
        if self._llmops is None:
            return None
        return await self._llmops.trace(
            name=prompt_name or operation_type,
            input_data={"messages": messages},
            output_data={"summary": output_summary},
            metadata={"operation_type": operation_type},
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        operation_type: str = "classify",
        prompt_name: str | None = None,
        input_content_ids: list[uuid.UUID] | None = None,
    ) -> LLMResponse:
        start = time.monotonic()
        response = await self._provider.complete(
            messages=messages,
            system=system,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        duration_ms = int((time.monotonic() - start) * 1000)

        trace_id = await self._trace(operation_type, prompt_name, messages, response.content[:500])
        await self._lineage.record(
            operation_type=operation_type,
            input_content_ids=input_content_ids,
            input_context_summary=messages[-1]["content"][:500] if messages else None,
            prompt_name=prompt_name,
            model=response.model,
            model_params={"temperature": temperature, "max_tokens": max_tokens},
            output_summary=response.content[:500],
            duration_ms=duration_ms,
            token_count_input=response.input_tokens,
            token_count_output=response.output_tokens,
            cost_usd=response.cost_usd,
            langfuse_trace_id=trace_id,
        )

        return response

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        operation_type: str = "classify",
        prompt_name: str | None = None,
        input_content_ids: list[uuid.UUID] | None = None,
    ) -> dict[str, Any]:
        start = time.monotonic()
        result = await self._provider.complete_structured(
            messages=messages,
            schema=schema,
            system=system,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        duration_ms = int((time.monotonic() - start) * 1000)

        trace_id = await self._trace(operation_type, prompt_name, messages, str(result)[:500])
        await self._lineage.record(
            operation_type=operation_type,
            input_content_ids=input_content_ids,
            prompt_name=prompt_name,
            model=model,
            output_summary=str(result)[:500],
            duration_ms=duration_ms,
            langfuse_trace_id=trace_id,
        )

        return result

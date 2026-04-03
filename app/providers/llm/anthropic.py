import json
from typing import Any

import anthropic

from app.config import settings
from app.providers.base import LLMResponse

# Cost per million tokens (approximate, as of 2026)
MODEL_COSTS = {
    "claude-sonnet-4-5-20250929": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
}


class AnthropicProvider:
    """LLM provider using Anthropic's Claude API."""

    def __init__(self, api_key: str | None = None):
        self._client = anthropic.AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)

    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        model = model or "claude-sonnet-4-5-20250929"
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens or 4096,
        }
        if system:
            kwargs["system"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature

        response = await self._client.messages.create(**kwargs)

        content = response.content[0].text if response.content else ""
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        costs = MODEL_COSTS.get(model, {"input": 3.0, "output": 15.0})
        cost_usd = (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000

        return LLMResponse(
            content=content,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Get a structured JSON response by instructing the model to output JSON."""
        json_instruction = f"\n\nRespond with valid JSON matching this schema:\n{json.dumps(schema, indent=2)}\n\nOutput ONLY the JSON, no other text."

        if system:
            system = system + json_instruction
        else:
            system = json_instruction

        response = await self.complete(
            messages=messages,
            system=system,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        return json.loads(text)

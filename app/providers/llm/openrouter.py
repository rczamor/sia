"""LLM provider for OpenRouter (OpenAI-compatible chat completions API).

Recommended default for self-hosted installs: one key, any model. Sia core uses
LLMs only for internal context operations (classification, consolidation,
synthesis), never end-user generation.
"""

import json
from typing import Any

import httpx

from app.providers.base import LLMResponse

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"


class OpenRouterProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        default_model: str = DEFAULT_MODEL,
        timeout: float = 120.0,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout = timeout

    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "max_tokens": max_tokens or 4096,
        }
        if temperature is not None:
            payload["temperature"] = temperature

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        usage = data.get("usage", {})
        return LLMResponse(
            content=data["choices"][0]["message"]["content"] or "",
            model=data.get("model", payload["model"]),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            # OpenRouter reports cost on the generation endpoint, not inline; left 0.
            cost_usd=float(usage.get("cost", 0.0) or 0.0),
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
        json_instruction = (
            "\n\nRespond with valid JSON matching this schema:\n"
            f"{json.dumps(schema, indent=2)}\n\nOutput ONLY the JSON, no other text."
        )
        system = (system + json_instruction) if system else json_instruction

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

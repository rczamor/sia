"""Deterministic in-process fakes for external providers (Ollama, Anthropic)."""

import hashlib
import math
from typing import Any

from app.providers.base import LLMResponse


class FakeEmbedding:
    """Deterministic 768-dim embeddings: a shared base direction plus a small
    text-dependent perturbation, so any two texts are highly similar (cosine ≈ 1)
    but not identical. Keeps similarity-threshold code paths realistic without a
    model server."""

    def __init__(self, dimensions: int = 768):
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def model_name(self) -> str:
        return "fake-embed"

    async def embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        vector = [1.0] * self._dimensions
        for i in range(self._dimensions):
            vector[i] += (digest[i % len(digest)] / 255.0) * 0.05
        norm = math.sqrt(sum(v * v for v in vector))
        return [v / norm for v in vector]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


class HashingEmbedder:
    """Bag-of-words hashing embedder: each token hashes to a dimension. Texts that
    share words are similar — real retrieval semantics, no model server."""

    def __init__(self, dimensions: int = 768):
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def model_name(self) -> str:
        return "hashing-embed"

    async def embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for token in text.lower().split():
            token = token.strip(".,;:!?()[]\"'")
            if not token:
                continue
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


class FakeLLM:
    """Canned LLM responses for classification/summarization paths."""

    def __init__(self, structured_response: dict[str, Any] | None = None):
        self.structured_response = structured_response or {
            "pillars": ["context_layers"],
            "summary": "A canned summary for testing.",
            "key_insights": ["insight one", "insight two"],
            "tags": ["testing"],
            "source_type": "article",
        }
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "system": system, "model": model})
        return LLMResponse(content="fake completion", model="fake-llm")

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"messages": messages, "schema": schema, "model": model})
        return self.structured_response

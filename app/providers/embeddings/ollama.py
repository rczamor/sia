import asyncio

import httpx

from app.config import settings


class OllamaEmbedding:
    """Embedding provider using Ollama's local API."""

    def __init__(self, model: str = "nomic-embed-text", base_url: str | None = None):
        self._model = model
        self._base_url = base_url or settings.ollama_url
        self._dimensions = 768

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base_url}/api/embeddings",
                json={"model": self._model, "prompt": text},
            )
            response.raise_for_status()
            return response.json()["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        tasks = [self.embed(text) for text in texts]
        return await asyncio.gather(*tasks)

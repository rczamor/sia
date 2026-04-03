from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def dimensions(self) -> int: ...

    @property
    def model_name(self) -> str: ...

    async def embed(self, text: str) -> list[float]: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@runtime_checkable
class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]: ...


@runtime_checkable
class LLMOpsProvider(Protocol):
    async def trace(
        self,
        name: str,
        input_data: dict | None = None,
        output_data: dict | None = None,
        metadata: dict | None = None,
    ) -> str | None: ...

    async def get_prompt(self, name: str, label: str = "production") -> str | None: ...

    async def score(
        self, trace_id: str, name: str, value: float, comment: str | None = None
    ) -> None: ...


@dataclass
class PublishResult:
    platform_post_id: str
    url: str | None = None


@dataclass
class PostMetrics:
    impressions: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    bookmarks: int = 0
    engagement_rate: float = 0.0


@runtime_checkable
class PublishingChannel(Protocol):
    @property
    def channel_name(self) -> str: ...

    async def publish(self, content: str, **kwargs) -> PublishResult: ...

    async def get_metrics(self, platform_post_id: str) -> PostMetrics: ...


@dataclass
class RawContent:
    title: str
    url: str
    content: str
    author: str | None = None
    published_at: str | None = None
    source_metadata: dict | None = None


@runtime_checkable
class IngestionSource(Protocol):
    @property
    def source_name(self) -> str: ...

    async def fetch_new_items(self, since: str | None = None) -> list[RawContent]: ...

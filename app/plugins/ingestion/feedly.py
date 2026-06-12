"""Feedly ingestion source: pulls saved/board items for the configured stream."""

from typing import Any

import httpx

from app.config import settings
from app.models.enums import PluginCategory
from app.plugins.base import PluginHealth, PluginInitError
from app.providers.base import RawContent

FEEDLY_API = "https://cloud.feedly.com/v3"


class FeedlyIngestion:
    plugin_id = "feedly"
    category = PluginCategory.INGESTION

    def __init__(self):
        self._token: str | None = None
        self._stream_id: str | None = None

    @property
    def provider(self) -> "FeedlyIngestion":
        return self

    @property
    def source_name(self) -> str:
        return "feedly"

    async def initialize(self, config: dict[str, Any]) -> None:
        if not settings.feedly_access_token:
            raise PluginInitError("FEEDLY_ACCESS_TOKEN is not set")
        if not settings.feedly_board_id:
            raise PluginInitError("FEEDLY_BOARD_ID is not set")
        self._token = settings.feedly_access_token
        self._stream_id = settings.feedly_board_id

    async def health_check(self) -> PluginHealth:
        if not self._token:
            return PluginHealth(healthy=False, message="not initialized")
        return PluginHealth(healthy=True)

    async def shutdown(self) -> None:
        self._token = None

    async def fetch_new_items(self, since: str | None = None) -> list[RawContent]:
        """Fetch stream items newer than `since` (epoch millis as string)."""
        params: dict[str, Any] = {"streamId": self._stream_id, "count": 50}
        if since:
            params["newerThan"] = since

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{FEEDLY_API}/streams/contents",
                params=params,
                headers={"Authorization": f"Bearer {self._token}"},
            )
            response.raise_for_status()
            data = response.json()

        items: list[RawContent] = []
        for entry in data.get("items", []):
            url = entry.get("canonicalUrl") or entry.get("alternate", [{}])[0].get("href")
            if not url:
                continue
            items.append(
                RawContent(
                    title=entry.get("title", "Untitled"),
                    url=url,
                    content=entry.get("content", {}).get("content", "")
                    or entry.get("summary", {}).get("content", ""),
                    author=entry.get("author"),
                    published_at=str(entry.get("published", "")),
                    source_metadata={"feedly_id": entry.get("id")},
                )
            )
        return items

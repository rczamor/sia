"""Google Docs ingestion source — absorb Docs INTO Sia instead of leaving them
as a sibling connector the harness reaches for first.

This is the source-absorption lever: when the operator's Google Docs flow into
Sia's data layer, the only path to that knowledge in any harness is
sia_build_context — there is no separate Google Docs tool to choose instead.

Reference adapter, dependency-free (httpx only, like the Feedly source). It reads
a pre-obtained OAuth access token from the environment with `drive.readonly`
scope and lists Google Docs modified since the last poll, exporting each as plain
text. Production deployments that need long-lived access should add token refresh
(service-account or refresh-token flow) in `initialize` — the rest of the adapter
is unchanged.

Freshness caveat: ingestion is eventually consistent. A doc edited seconds ago is
not yet consolidated, so a harness asking about it has a legitimate reason to look
elsewhere. Tune the poll interval (and rely on the labeled raw fallback) to keep
the window small; that window is the real cost of absorption versus a live
connector.
"""

from typing import Any

import httpx

from app.config import settings
from app.models.enums import PluginCategory
from app.plugins.base import PluginHealth, PluginInitError
from app.providers.base import RawContent

DRIVE_API = "https://www.googleapis.com/drive/v3"
DOC_MIME = "application/vnd.google-apps.document"


class GoogleDocsIngestion:
    plugin_id = "gdocs"
    category = PluginCategory.INGESTION

    def __init__(self):
        self._token: str | None = None
        self._folder_id: str | None = None

    @property
    def provider(self) -> "GoogleDocsIngestion":
        return self

    @property
    def source_name(self) -> str:
        return "gdocs"

    async def initialize(self, config: dict[str, Any]) -> None:
        if not settings.google_drive_access_token:
            raise PluginInitError("GOOGLE_DRIVE_ACCESS_TOKEN is not set")
        self._token = settings.google_drive_access_token
        # Optional: scope ingestion to one folder. Empty = the whole drive.
        self._folder_id = settings.google_drive_folder_id or None

    async def health_check(self) -> PluginHealth:
        if not self._token:
            return PluginHealth(healthy=False, message="not initialized")
        return PluginHealth(healthy=True)

    async def shutdown(self) -> None:
        self._token = None

    async def fetch_new_items(self, since: str | None = None) -> list[RawContent]:
        """List Google Docs modified after `since` (RFC3339 timestamp) and export
        each as plain text."""
        clauses = [f"mimeType = '{DOC_MIME}'", "trashed = false"]
        if since:
            clauses.append(f"modifiedTime > '{since}'")
        if self._folder_id:
            clauses.append(f"'{self._folder_id}' in parents")
        params = {
            "q": " and ".join(clauses),
            "fields": "files(id,name,modifiedTime,webViewLink,owners(displayName))",
            "pageSize": 50,
            "orderBy": "modifiedTime desc",
        }
        headers = {"Authorization": f"Bearer {self._token}"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            listing = await client.get(f"{DRIVE_API}/files", params=params, headers=headers)
            listing.raise_for_status()
            files = listing.json().get("files", [])

            items: list[RawContent] = []
            for entry in files:
                body = await self._export_text(client, entry["id"], headers)
                if not body:
                    continue
                owners = entry.get("owners") or []
                items.append(
                    RawContent(
                        title=entry.get("name", "Untitled doc"),
                        url=entry.get("webViewLink")
                        or f"https://docs.google.com/document/d/{entry['id']}",
                        content=body,
                        author=owners[0].get("displayName") if owners else None,
                        published_at=entry.get("modifiedTime", ""),
                        source_metadata={"gdoc_id": entry["id"]},
                    )
                )
        return items

    async def _export_text(
        self, client: httpx.AsyncClient, file_id: str, headers: dict[str, str]
    ) -> str:
        response = await client.get(
            f"{DRIVE_API}/files/{file_id}/export",
            params={"mimeType": "text/plain"},
            headers=headers,
        )
        response.raise_for_status()
        return response.text

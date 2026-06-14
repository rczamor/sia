import logging
import uuid

import httpx
import trafilatura
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.quarantine import quarantine_reason
from app.prompts.source_analyst import CLASSIFY_AND_SUMMARIZE
from app.providers.base import EmbeddingProvider
from app.data.knowledge_store import KnowledgeStore
from app.data.lineage import TrackedLLMProvider
from app.data.url_safety import UnsafeURLError, fetch_public_url
from app.data.versioning import VersioningService

logger = logging.getLogger(__name__)


class IngestionService:
    """Orchestrates the full ingestion pipeline: fetch → classify → summarize → embed → store."""

    def __init__(
        self,
        db: AsyncSession,
        llm: TrackedLLMProvider,
        embedder: EmbeddingProvider,
        classify_params: dict | None = None,
    ):
        self.db = db
        self.llm = llm
        self.store = KnowledgeStore(db, embedder)
        self.versioning = VersioningService(db)
        # Model selection for classification comes from ai_config (llm_classification).
        self.classify_params = classify_params or {}
        self.classify_model = self.classify_params.get("model", "claude-haiku-4-5-20251001")
        self.classify_temperature = self.classify_params.get("temperature", 0.3)

    async def ingest_url(
        self,
        url: str,
        notes: str | None = None,
        pillar_override: list[str] | None = None,
        trust_tier: str | None = None,
    ) -> dict:
        # 1. Dedup check
        if await self.store.url_exists(url):
            return {"error": "URL already exists in knowledge base", "url": url}

        # 2. Fetch content (SSRF-guarded: scheme allowlist, public hosts only,
        #    redirects re-validated per hop)
        try:
            downloaded = await fetch_public_url(url)
        except UnsafeURLError as exc:
            return {"error": f"URL refused: {exc}", "url": url}
        except httpx.HTTPError as exc:
            return {"error": f"Could not fetch URL content: {exc}", "url": url}
        if not downloaded:
            return {"error": "Could not fetch URL content", "url": url}

        extracted = trafilatura.extract(
            downloaded, include_comments=False, include_tables=True, output_format="txt"
        )
        if not extracted:
            return {"error": "Could not extract content from URL", "url": url}

        metadata = trafilatura.extract(
            downloaded, output_format="json", include_comments=False
        )
        title = "Untitled"
        author = None
        if metadata:
            import json
            try:
                meta = json.loads(metadata)
                title = meta.get("title", "Untitled")
                author = meta.get("author")
            except (json.JSONDecodeError, TypeError):
                pass

        return await self.ingest_content(
            title=title,
            url=url,
            content=extracted,
            author=author,
            notes=notes,
            pillar_override=pillar_override,
            # Owner-supplied notes (via /api/ingest/url) imply curation; callers
            # that can't vouch for the source (the webhook) pass trust_tier
            # explicitly so a self-asserted provenance note can't elevate tier.
            trust_tier=trust_tier if trust_tier is not None else ("curated" if notes else "untrusted"),
            dedup=False,  # already checked above
        )

    async def ingest_content(
        self,
        title: str,
        content: str,
        url: str | None = None,
        author: str | None = None,
        notes: str | None = None,
        pillar_override: list[str] | None = None,
        trust_tier: str = "untrusted",
        dedup: bool = True,
    ) -> dict:
        """Run the classify → quarantine → store → version pipeline on content
        already in hand (e.g. a Google Doc exported by an ingestion source whose
        URL is auth-gated and can't be re-fetched by the public-URL fetcher).
        Absorbed external-system content defaults to the untrusted tier, so it
        passes the review gate before it can be consolidated."""
        if dedup and url and await self.store.url_exists(url):
            return {"error": "URL already exists in knowledge base", "url": url}
        if not content:
            return {"error": "No content to ingest", "url": url}

        # 3. LLM classify + summarize
        prompt = CLASSIFY_AND_SUMMARIZE.format(
            title=title, content=content[:6000]
        )
        analysis = await self.llm.complete_structured(
            messages=[{"role": "user", "content": prompt}],
            schema={
                "pillars": ["string"],
                "summary": "string",
                "key_insights": ["string"],
                "tags": ["string"],
                "source_type": "string",
            },
            model=self.classify_model,
            temperature=self.classify_temperature,
            operation_type="classify",
            prompt_name="source_analyst",
        )

        pillars = pillar_override or analysis.get("pillars", ["context_layers"])
        summary = analysis.get("summary", "")
        tags = analysis.get("tags", [])
        source_type = analysis.get("source_type", "article")

        # 4. Quarantine screen: injection markers, oversize, off-domain content is
        # stored for audit but never consolidated until an operator clears it.
        reason = quarantine_reason(content, pillars=analysis.get("pillars"))

        # 5. Store in knowledge base (embedding happens inside add_source).
        # Trust tier is decided by the caller: an annotated item passed through
        # human hands is curated; a bare URL, feed item, or absorbed document is
        # untrusted until the review gate clears it.
        item = await self.store.add_source(
            title=title,
            url=url,
            content=content,
            summary=summary,
            pillar=pillars,
            source_type=source_type,
            author=author,
            your_notes=notes,
            tags=tags,
            trust_tier=trust_tier,
            quarantined=reason is not None,
        )
        if reason:
            logger.warning("Quarantined source %s (%s): %s", item.id, url, reason)

        # 6. Create version record. Include `content` so a restore to this initial
        # version is complete (and re-embeds from a fully-restored state rather than
        # blending old metadata with whatever content is current).
        await self.versioning.create_version(
            entity_type="source_content",
            entity_id=item.id,
            content_snapshot={
                "title": title, "url": url, "summary": summary, "content": content,
                "pillar": pillars, "source_type": source_type, "tags": tags,
            },
            change_type="create",
        )

        await self.db.commit()

        # Related-item discovery is a Retrieval-layer concern; the API layer
        # composes it onto this result.
        return {
            "id": str(item.id),
            "title": title,
            "summary": summary,
            "pillar": pillars,
            "tags": tags,
            "source_type": source_type,
            "quarantined": reason,
        }

    async def ingest_thought(
        self,
        content: str,
        pillar: list[str] | None = None,
        thought_type: str = "idea",
        related_source_ids: list[uuid.UUID] | None = None,
    ) -> dict:
        # Auto-classify if no pillar provided
        if not pillar:
            analysis = await self.llm.complete_structured(
                messages=[{"role": "user", "content": f"Classify this thought into pillars: {content[:2000]}"}],
                schema={"pillars": ["string"]},
                model=self.classify_model,
                temperature=self.classify_temperature,
                operation_type="classify",
                prompt_name="thought_classifier",
            )
            pillar = analysis.get("pillars", ["context_layers"])

        item = await self.store.add_thought(
            content=content,
            pillar=pillar,
            thought_type=thought_type,
            related_source_ids=related_source_ids,
        )

        await self.versioning.create_version(
            entity_type="my_thoughts",
            entity_id=item.id,
            content_snapshot={"content": content, "pillar": pillar, "thought_type": thought_type},
            change_type="create",
        )

        await self.db.commit()

        return {
            "id": str(item.id),
            "content": content[:200],
            "pillar": pillar,
            "thought_type": thought_type,
        }

    async def ingest_artifact(
        self,
        title: str,
        content: str,
        artifact_type: str = "framework",
        domain: str | None = None,
        pillar: list[str] | None = None,
    ) -> dict:
        if not pillar:
            pillar = ["context_layers"]

        item = await self.store.add_artifact(
            title=title,
            content=content,
            artifact_type=artifact_type,
            domain=domain,
            pillar=pillar,
        )

        await self.versioning.create_version(
            entity_type="expertise_artifacts",
            entity_id=item.id,
            content_snapshot={"title": title, "pillar": pillar, "artifact_type": artifact_type},
            change_type="create",
        )

        await self.db.commit()

        return {
            "id": str(item.id),
            "title": title,
            "pillar": pillar,
            "artifact_type": artifact_type,
        }

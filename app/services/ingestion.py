import uuid

import trafilatura
from sqlalchemy.ext.asyncio import AsyncSession

from app.prompts.source_analyst import CLASSIFY_AND_SUMMARIZE
from app.providers.base import EmbeddingProvider
from app.services.knowledge_store import KnowledgeStore
from app.services.lineage import LineageService, TrackedLLMProvider
from app.services.versioning import VersioningService


class IngestionService:
    """Orchestrates the full ingestion pipeline: fetch → classify → summarize → embed → store."""

    def __init__(
        self,
        db: AsyncSession,
        llm: TrackedLLMProvider,
        embedder: EmbeddingProvider,
    ):
        self.db = db
        self.llm = llm
        self.store = KnowledgeStore(db, embedder)
        self.versioning = VersioningService(db)

    async def ingest_url(
        self,
        url: str,
        notes: str | None = None,
        pillar_override: list[str] | None = None,
    ) -> dict:
        # 1. Dedup check
        if await self.store.url_exists(url):
            return {"error": "URL already exists in knowledge base", "url": url}

        # 2. Fetch content
        downloaded = trafilatura.fetch_url(url)
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

        # 3. LLM classify + summarize
        prompt = CLASSIFY_AND_SUMMARIZE.format(
            title=title, content=extracted[:6000]
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
            model="claude-haiku-4-5-20251001",
            temperature=0.3,
            operation_type="classify",
            prompt_name="source_analyst",
        )

        pillars = pillar_override or analysis.get("pillars", ["context_layers"])
        summary = analysis.get("summary", "")
        tags = analysis.get("tags", [])
        source_type = analysis.get("source_type", "article")

        # 4. Store in knowledge base (embedding happens inside add_source)
        item = await self.store.add_source(
            title=title,
            url=url,
            content=extracted,
            summary=summary,
            pillar=pillars,
            source_type=source_type,
            author=author,
            your_notes=notes,
            tags=tags,
        )

        # 5. Create version record
        await self.versioning.create_version(
            entity_type="source_content",
            entity_id=item.id,
            content_snapshot={
                "title": title, "url": url, "summary": summary,
                "pillar": pillars, "source_type": source_type, "tags": tags,
            },
            change_type="create",
        )

        # 6. Find related items
        related = await self.store.hybrid_search(
            query=f"{title} {summary}", limit=5
        )
        # Filter out self
        related = [r for r in related if r["id"] != item.id]

        await self.db.commit()

        return {
            "id": str(item.id),
            "title": title,
            "summary": summary,
            "pillar": pillars,
            "tags": tags,
            "source_type": source_type,
            "related": related[:5],
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
                model="claude-haiku-4-5-20251001",
                temperature=0.3,
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

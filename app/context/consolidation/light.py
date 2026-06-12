"""Light clock: post-ingest matching of new data-layer items into topic files.

Trust gate: if every input is owner-tier the commit goes to main; anything touched
by curated/untrusted intake lands on the day's ``consolidation/<date>`` review
branch. Sources are marked consolidated immediately for main commits, and at
review-approval time for branch commits (consolidation_runs carries the linkage).
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.consolidation.base import fail_run, finish_run, start_run
from app.context.graph import GraphService
from app.context.index import StoreIndexer
from app.context.store.documents import MarkdownSerializer, StoreDocument
from app.context.store.gitstore import GitContextStore
from app.data.lineage import TrackedLLMProvider
from app.models.tables import SourceContent
from app.prompts.consolidation import LIGHT_MATCH
from app.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

MAX_ITEMS_PER_RUN = 20
CANDIDATE_TOPICS = 5


def new_topic_document(
    slug: str, title: str, pillar: str, gist: str, claims: list[str], source_id: uuid.UUID
) -> StoreDocument:
    today = datetime.now(timezone.utc).date().isoformat()
    front = {
        "id": f"topic-{slug}",
        "pillar": pillar,
        "type": "topic",
        "status": "active",
        "confidence": 0.5,
        "priority": 0.5,
        "visibility": "private",
        "freshness": today,
        "last_consolidated": today,
        "sources": [str(source_id)],
        "related": [],
    }
    claim_lines = "\n".join(f"- {c} [source:{source_id}]" for c in claims)
    body = (
        f"# {title}\n\n## Gist\n\n{gist}\n\n## Key claims\n\n{claim_lines}\n\n"
        f"## Tensions\n\n## Implications\n"
    )
    return StoreDocument(path=f"knowledge/{pillar}/{slug}.md", front=front, body=body)


class LightClock:
    def __init__(
        self,
        db: AsyncSession,
        store: GitContextStore,
        llm: TrackedLLMProvider,
        embedder: EmbeddingProvider,
        llm_params: dict | None = None,
    ):
        self.db = db
        self.store = store
        self.llm = llm
        self.embedder = embedder
        self.llm_params = llm_params or {}
        self.serializer = MarkdownSerializer()

    async def run(self, source_ids: list[uuid.UUID] | None = None) -> dict:
        query = select(SourceContent).where(
            SourceContent.is_consolidated.is_(False), SourceContent.quarantined.is_(False)
        )
        if source_ids:
            query = query.where(SourceContent.id.in_(source_ids))
        sources = (
            (await self.db.execute(query.limit(MAX_ITEMS_PER_RUN))).scalars().all()
        )
        run = await start_run(self.db, "light", [s.id for s in sources])
        try:
            result = await self._consolidate(run, sources)
            await self.db.commit()
            return result
        except Exception as exc:
            await fail_run(self.db, run, exc)
            await self.db.commit()
            raise

    async def _consolidate(self, run, sources) -> dict:
        if not sources:
            await finish_run(self.db, run, [], "no unconsolidated items")
            return {"processed": 0, "files_changed": []}

        all_owner_tier = all(s.trust_tier == "owner" for s in sources)
        branch = (
            None
            if all_owner_tier
            else f"consolidation/{datetime.now(timezone.utc).date().isoformat()}"
        )

        files: dict[str, str] = {}
        processed = 0
        for source in sources:
            decision = await self._match(source)
            action = decision.get("action", "skip")
            claims = [c for c in decision.get("claims", []) if c][:4]
            if action == "skip" or not claims:
                source.is_consolidated = True  # nothing to extract is a terminal state
                continue

            if action == "append" and decision.get("topic_path"):
                path = decision["topic_path"]
                updated = await self._append_claims(path, files.get(path), claims, source.id)
                if updated is None:
                    action = "new_topic"  # topic path didn't resolve; fall through
                else:
                    files[path] = updated
            if action == "new_topic":
                proposal = decision.get("new_topic") or {}
                slug = proposal.get("slug") or f"untitled-{str(source.id)[:8]}"
                document = new_topic_document(
                    slug=slug,
                    title=proposal.get("title") or source.title,
                    pillar=proposal.get("pillar") or (source.pillar or ["context_layers"])[0],
                    gist=proposal.get("gist") or (source.summary or "")[:300],
                    claims=claims,
                    source_id=source.id,
                )
                files[document.path] = self.serializer.dumps(document)

            processed += 1
            if branch is None:
                source.is_consolidated = True

        if not files:
            await finish_run(self.db, run, [], f"{processed} items, no file changes")
            return {"processed": processed, "files_changed": []}

        message = f"light: consolidate {processed} item(s)"
        await self.store.commit(files, message, branch=branch)

        if branch is None:
            # direct-to-main: re-index + refresh declared edges immediately
            indexer = StoreIndexer(self.db, self.store, self.embedder)
            indexed = await indexer.sync()
            graph = GraphService(self.db)
            for path in files:
                content = await self.store.read(path)
                if content:
                    document = self.serializer.loads(path, content)
                    await graph.sync_document_edges(document, indexed, run_id=run.id)

        await finish_run(
            self.db, run, sorted(files), f"{processed} item(s) -> {len(files)} file(s)", branch
        )
        return {"processed": processed, "files_changed": sorted(files), "branch": branch}

    async def _match(self, source) -> dict:
        candidates = await self._candidate_topics(source)
        candidate_text = (
            "\n".join(f"- {path} :: {gist}" for path, gist in candidates) or "(none yet)"
        )
        prompt = LIGHT_MATCH.format(
            candidates=candidate_text,
            source_id=source.id,
            source_type=source.source_type,
            title=source.title,
            summary=source.summary or "",
            excerpt=(source.content or "")[:3000],
            pillar=(source.pillar or ["context_layers"])[0],
        )
        return await self.llm.complete_structured(
            messages=[{"role": "user", "content": prompt}],
            schema={"action": "string", "topic_path": "string", "new_topic": {}, "claims": []},
            operation_type="consolidate",
            prompt_name="light_match",
            input_content_ids=[source.id],
            **self.llm_params,
        )

    async def _candidate_topics(self, source) -> list[tuple[str, str]]:
        if source.embedding is None:
            return []
        rows = await self.db.execute(
            text(
                """
                SELECT path, gist FROM context_sections
                WHERE kind = 'topic' AND status != 'archived'
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :k
                """
            ),
            {"vec": str([float(v) for v in source.embedding]), "k": CANDIDATE_TOPICS},
        )
        return [(row.path, row.gist or "") for row in rows]

    async def _append_claims(
        self, path: str, pending: str | None, claims: list[str], source_id: uuid.UUID
    ) -> str | None:
        content = pending or await self.store.read(path)
        if content is None:
            return None
        document = self.serializer.loads(path, content)
        claim_lines = "\n".join(f"- {c} [source:{source_id}]" for c in claims)
        section = document.section("Key claims")
        new_section = f"{section}\n{claim_lines}".strip()
        document.body = _replace_section(document.body, "Key claims", new_section)
        today = datetime.now(timezone.utc).date().isoformat()
        document.front["freshness"] = today
        document.front["last_consolidated"] = today
        existing_sources = [str(s) for s in document.front.get("sources") or []]
        if str(source_id) not in existing_sources:
            document.front["sources"] = existing_sources + [str(source_id)]
        return self.serializer.dumps(document)


def _replace_section(body: str, heading: str, new_content: str) -> str:
    lines = body.split("\n")
    output: list[str] = []
    inside = False
    replaced = False
    for line in lines:
        if line.strip().lower() == f"## {heading}".lower():
            inside = True
            replaced = True
            output.append(line)
            output.append("")
            output.append(new_content)
            continue
        if inside and line.startswith("## "):
            inside = False
            output.append("")
        if not inside:
            output.append(line)
    if not replaced:
        output.extend(["", f"## {heading}", "", new_content])
    return "\n".join(output)

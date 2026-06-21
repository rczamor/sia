"""Deep clock (weekly): entity linking across pillars, pruning, skill synthesis.

- Entities bridge topics across pillars (the cross-cutting-pattern substrate).
- Pruning is a status transition + commit, never deletion.
- Skill synthesis drafts procedural knowledge (skills/<slug>/SKILL.md) from
  observed practice — always on a review branch: skills change agent behavior,
  so a human approves every draft.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.consolidation.base import fail_run, finish_run, start_run
from app.context.entities import EntityExtractor
from app.context.index import StoreIndexer
from app.context.store.documents import MarkdownSerializer, StoreDocument, safe_slug
from app.context.store.gitstore import GitContextStore
from app.data.lineage import TrackedLLMProvider
from app.models.tables import ContextSections, ExpertiseArtifacts
from app.prompts.consolidation import DEEP_SKILL
from app.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

STALE_AFTER_DAYS = 90
STALE_PRIORITY_CEILING = 0.3


class DeepClock:
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

    async def run(self) -> dict:
        run = await start_run(self.db, "deep")
        try:
            result = await self._consolidate(run)
            await self.db.commit()
            return result
        except Exception as exc:
            await fail_run(self.db, run, exc)
            await self.db.commit()
            raise

    async def _consolidate(self, run) -> dict:
        files_main: dict[str, str] = {}

        # 1. Entity linking across topics (all active topics, batched)
        entities_added = await self._extract_entities(run)

        # 2. Pruning: stale topics get a status transition (archive commit)
        pruned = await self._prune(files_main)

        if files_main:
            await self.store.commit(files_main, "deep: prune stale topics")

        # 3. Skill synthesis — always on a review branch
        branch = f"consolidation/{datetime.now(timezone.utc).date().isoformat()}-skills"
        skill_path = await self._synthesize_skill(branch)

        # 4. Re-index
        indexer = StoreIndexer(self.db, self.store, self.embedder)
        await indexer.sync()

        # 5. Regression suite against the post-consolidation store
        regression_summary = await self._run_regression()

        changed = sorted(files_main) + ([skill_path] if skill_path else [])
        summary = (
            f"{entities_added} entities, {pruned} pruned, "
            f"skill draft: {skill_path or 'none'}, regression: {regression_summary}"
        )
        await finish_run(
            self.db, run, changed, summary, branch=branch if skill_path else None
        )
        return {
            "entities": entities_added,
            "pruned": pruned,
            "skill_draft": skill_path,
            "files_changed": changed,
        }

    async def _run_regression(self) -> str:
        from app.context.builder import ContextBuilder
        from app.context.consolidation.base import send_alert
        from app.context.quality import run_regression

        builder = ContextBuilder(self.db, self.store, self.embedder)
        results = await run_regression(self.db, self.store, builder)
        if not results:
            return "no fixtures"
        failed = [r for r in results if not r.passed]
        if failed:
            details = "; ".join(
                f"{r.fixture} missing {r.missing_paths} (coverage {r.coverage:.2f})"
                for r in failed[:5]
            )
            await send_alert(
                f":warning: Sia regression: {len(failed)}/{len(results)} golden builds "
                f"failed after deep consolidation — {details}"
            )
        return f"{len(results) - len(failed)}/{len(results)} passed"

    async def _extract_entities(self, run) -> int:
        """Entity linking across EVERY active topic (batched), feeding gist + claims
        through the shared extractor with semantic dedup and entity relations."""
        rows = (
            (
                await self.db.execute(
                    select(ContextSections)
                    .where(ContextSections.kind == "topic", ContextSections.status == "active")
                    .order_by(ContextSections.priority.desc())
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return 0
        extractor = EntityExtractor(
            self.db, self.store, self.llm, self.embedder, llm_params=self.llm_params
        )
        return await extractor.extract_for_topics(list(rows), run.id)

    async def _prune(self, files: dict[str, str]) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_AFTER_DAYS)
        rows = (
            (
                await self.db.execute(
                    select(ContextSections).where(
                        ContextSections.kind == "topic",
                        ContextSections.status == "active",
                        ContextSections.priority <= STALE_PRIORITY_CEILING,
                        ContextSections.freshness < cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        pruned = 0
        for row in rows:
            content = await self.store.read(row.path)
            if not content:
                continue
            document = self.serializer.loads(row.path, content)
            document.front["status"] = "stale"
            files[row.path] = self.serializer.dumps(document)
            pruned += 1
        return pruned

    async def _synthesize_skill(self, branch: str) -> str | None:
        artifacts = (
            (
                await self.db.execute(
                    select(ExpertiseArtifacts)
                    .order_by(ExpertiseArtifacts.created_at.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        if not artifacts:
            return None
        lineage_stats = (
            await self.db.execute(
                text(
                    "SELECT operation_type, count(*) AS n FROM process_lineage "
                    "GROUP BY operation_type ORDER BY n DESC LIMIT 10"
                )
            )
        ).mappings()
        stats_text = "\n".join(f"- {r['operation_type']}: {r['n']} calls" for r in lineage_stats)
        artifacts_text = "\n\n".join(
            f"[artifact:{a.id}] {a.title}\n{a.content[:1200]}" for a in artifacts
        )
        prompt_template = await self.llm.prompt("deep_skill", DEEP_SKILL)
        response = await self.llm.complete_structured(
            messages=[
                {
                    "role": "user",
                    "content": prompt_template.format(
                        artifacts=artifacts_text, lineage_stats=stats_text or "(none)"
                    ),
                }
            ],
            schema={"slug": "string", "title": "string", "trigger_description": "string",
                    "steps": [], "failure_modes": [], "derived_from": []},
            operation_type="consolidate",
            prompt_name="deep_skill",
            **self.llm_params,
        )
        slug = response.get("slug")
        if not slug:
            return None
        document = skill_document(response)
        await self.store.commit(
            {document.path: self.serializer.dumps(document)},
            f"deep: draft skill {slug}",
            branch=branch,
        )
        return document.path


def skill_document(spec: dict) -> StoreDocument:
    today = datetime.now(timezone.utc).date().isoformat()
    slug = safe_slug(spec["slug"], fallback="skill")  # builds the store path
    steps = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(spec.get("steps") or []))
    failures = "\n".join(f"- {f}" for f in spec.get("failure_modes") or [])
    body = (
        f"# {spec.get('title', slug)}\n\n## Procedure\n\n{steps}\n\n"
        f"## Failure modes\n\n{failures}\n"
    )
    front = {
        "id": f"skill-{slug}",
        "type": "skill",
        "status": "active",
        "memento_contract_version": "1.0",
        "progressive_disclosure": True,
        "maturity": "draft",
        "priority": 0.5,
        "visibility": "private",
        "freshness": today,
        "trigger_description": spec.get("trigger_description", ""),
        "token_cost_estimate": max(1, len(body) // 4),
        "derived_from": spec.get("derived_from") or [],
    }
    return StoreDocument(path=f"skills/{slug}/SKILL.md", front=front, body=body)

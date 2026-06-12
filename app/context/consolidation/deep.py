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
from app.context.graph import GraphService, file_ref
from app.context.index import StoreIndexer
from app.context.store.documents import MarkdownSerializer, StoreDocument
from app.context.store.gitstore import GitContextStore
from app.data.lineage import TrackedLLMProvider
from app.models.tables import ContextSections, Entities, ExpertiseArtifacts
from app.prompts.consolidation import DEEP_ENTITIES, DEEP_SKILL
from app.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

STALE_AFTER_DAYS = 90
STALE_PRIORITY_CEILING = 0.3
MAX_TOPICS_FOR_ENTITIES = 40


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
        graph = GraphService(self.db)

        # 1. Entity linking across topics
        entities_added = await self._extract_entities(graph, run)

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

        changed = sorted(files_main) + ([skill_path] if skill_path else [])
        summary = (
            f"{entities_added} entities, {pruned} pruned, "
            f"skill draft: {skill_path or 'none'}"
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

    async def _extract_entities(self, graph: GraphService, run) -> int:
        rows = (
            (
                await self.db.execute(
                    select(ContextSections)
                    .where(ContextSections.kind == "topic", ContextSections.status == "active")
                    .order_by(ContextSections.priority.desc())
                    .limit(MAX_TOPICS_FOR_ENTITIES)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return 0
        topics_text = "\n".join(f"- {r.path} :: {r.gist or ''}" for r in rows)
        response = await self.llm.complete_structured(
            messages=[{"role": "user", "content": DEEP_ENTITIES.format(topics=topics_text)}],
            schema={"entities": []},
            operation_type="consolidate",
            prompt_name="deep_entities",
            **self.llm_params,
        )
        known_paths = {r.path for r in rows}
        added = 0
        for item in response.get("entities") or []:
            name = (item.get("name") or "").strip()
            if not name:
                continue
            entity = (
                await self.db.execute(select(Entities).where(Entities.name == name))
            ).scalar_one_or_none()
            if entity is None:
                entity = Entities(
                    name=name,
                    entity_type=item.get("type", "concept"),
                    embedding=await self.embedder.embed(name),
                )
                self.db.add(entity)
                await self.db.flush()
                added += 1
            for path in item.get("mentioned_in") or []:
                if path in known_paths:
                    await graph.upsert_edge(
                        file_ref(path), "mentions", f"entity:{entity.id}", run_id=run.id
                    )
        return added

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
        response = await self.llm.complete_structured(
            messages=[
                {
                    "role": "user",
                    "content": DEEP_SKILL.format(
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
    slug = spec["slug"]
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
        "maturity": "draft",
        "priority": 0.5,
        "visibility": "private",
        "freshness": today,
        "trigger_description": spec.get("trigger_description", ""),
        "token_cost_estimate": max(1, len(body) // 4),
        "derived_from": spec.get("derived_from") or [],
    }
    return StoreDocument(path=f"skills/{slug}/SKILL.md", front=front, body=body)

"""REM clock (daily): merge and re-gist recently changed topics, surface
contradictions into tensions/, refresh the INDEX.

Operates only on main (already-trusted content), so it commits directly.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.consolidation.base import fail_run, finish_run, start_run
from app.context.graph import GraphService, file_ref
from app.context.index import StoreIndexer
from app.context.store.documents import MarkdownSerializer
from app.context.store.gitstore import GitContextStore
from app.data.lineage import TrackedLLMProvider
from app.models.tables import ContextSections
from app.prompts.consolidation import REM_CONTRADICTIONS, REM_GIST
from app.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

CHANGED_WINDOW_HOURS = 26
MAX_REGIST_TOPICS = 15
MAX_CONTRADICTION_PAIRS = 5


class RemClock:
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
        run = await start_run(self.db, "rem")
        try:
            result = await self._consolidate(run)
            await self.db.commit()
            return result
        except Exception as exc:
            await fail_run(self.db, run, exc)
            await self.db.commit()
            raise

    async def _consolidate(self, run) -> dict:
        # Re-index first so context_sections reflects the store (including any
        # review merges since the last run).
        indexer = StoreIndexer(self.db, self.store, self.embedder)
        indexed = await indexer.sync(regenerate_index=False)

        files: dict[str, str] = {}
        changed = await self._recently_changed_topics()

        # 1. Regenerate gists for changed topics
        for row in changed[:MAX_REGIST_TOPICS]:
            content = await self.store.read(row.path)
            if not content:
                continue
            document = self.serializer.loads(row.path, content)
            claims = document.section("Key claims")
            if not claims:
                continue
            response = await self.llm.complete_structured(
                messages=[
                    {
                        "role": "user",
                        "content": REM_GIST.format(title=row.title or row.path, claims=claims),
                    }
                ],
                schema={"gist": "string"},
                operation_type="consolidate",
                prompt_name="rem_gist",
                **self.llm_params,
            )
            gist = (response.get("gist") or "").strip()
            if gist:
                document.body = _set_gist(document.body, gist)
                files[row.path] = self.serializer.dumps(document)

        # 2. Contradiction pass over similar same-pillar topic pairs
        contradictions = await self._find_contradictions(changed, run)
        if contradictions:
            files["tensions/contradictions.md"] = await self._render_tensions(contradictions)

        # 3. Citation-use ledger: priorities follow demonstrated usefulness
        ledger_changes = await self._apply_citation_ledger(files)

        if files:
            await self.store.commit(files, "rem: re-gist + tensions", branch=None)

        # 4. Refresh index + INDEX.md (always — freshness decay moves daily)
        await indexer.sync()

        # 5. Refresh declared graph edges for changed files
        graph = GraphService(self.db)
        for path in files:
            content = await self.store.read(path)
            if content:
                await graph.sync_document_edges(
                    self.serializer.loads(path, content), indexed, run_id=run.id
                )

        # 6. Incremental entity extraction for changed topics — so new topics get
        # entities daily instead of waiting for the weekly deep clock.
        entities_added = await self._extract_entities_for_changed(changed, run)

        summary = (
            f"re-gisted {len(files)} file(s), {len(contradictions)} contradiction(s), "
            f"{ledger_changes} priority adjustment(s), {entities_added} entity(ies)"
        )
        await finish_run(self.db, run, sorted(files), summary)
        return {
            "files_changed": sorted(files),
            "contradictions": len(contradictions),
            "priority_adjustments": ledger_changes,
            "entities_added": entities_added,
        }

    async def _extract_entities_for_changed(self, changed, run) -> int:
        topics = [r for r in changed if r.kind == "topic" and r.status == "active"]
        if not topics:
            return 0
        from app.context.entities import EntityExtractor

        extractor = EntityExtractor(
            self.db, self.store, self.llm, self.embedder, llm_params=self.llm_params
        )
        return await extractor.extract_for_topics(topics, run.id)

    async def _apply_citation_ledger(self, files: dict[str, str]) -> int:
        """Topics served in builds flagged useful gain priority; flagged-useless
        lose it. Demonstrated usage, not assumed importance, drives ranking."""
        from sqlalchemy import text as sql_text

        rows = (
            await self.db.execute(
                sql_text(
                    """
                    SELECT served, flags FROM context_builds
                    WHERE created_at > now() - interval '7 days'
                      AND flags ? 'useful' AND NOT (flags ? 'ledger_applied')
                    """
                )
            )
        ).mappings().all()
        deltas: dict[str, float] = {}
        for row in rows:
            delta = 0.05 if row["flags"].get("useful") else -0.05
            for item in row["served"] or []:
                path = item.get("path", "")
                if path.startswith(("knowledge/", "skills/")):
                    deltas[path] = deltas.get(path, 0.0) + delta

        changed = 0
        for path, delta in deltas.items():
            content = files.get(path) or await self.store.read(path)
            if not content:
                continue
            document = self.serializer.loads(path, content)
            current = float(document.front.get("priority", 0.5))
            updated = max(0.1, min(1.0, current + delta))
            if abs(updated - current) < 1e-9:
                continue
            document.front["priority"] = round(updated, 2)
            files[path] = self.serializer.dumps(document)
            changed += 1

        if rows:
            await self.db.execute(
                sql_text(
                    """
                    UPDATE context_builds
                    SET flags = flags || '{"ledger_applied": true}'::jsonb
                    WHERE created_at > now() - interval '7 days'
                      AND flags ? 'useful' AND NOT (flags ? 'ledger_applied')
                    """
                )
            )
        return changed

    async def _recently_changed_topics(self):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=CHANGED_WINDOW_HOURS)
        return (
            (
                await self.db.execute(
                    select(ContextSections)
                    .where(
                        ContextSections.kind == "topic",
                        ContextSections.status == "active",
                        ContextSections.updated_at >= cutoff,
                    )
                    .order_by(ContextSections.priority.desc())
                )
            )
            .scalars()
            .all()
        )

    async def _find_contradictions(self, changed, run) -> list[dict]:
        contradictions: list[dict] = []
        graph = GraphService(self.db)
        pairs = 0
        for row in changed:
            if pairs >= MAX_CONTRADICTION_PAIRS:
                break
            peer = await self._nearest_peer(row)
            if peer is None:
                continue
            pairs += 1
            content_a = await self.store.read(row.path)
            content_b = await self.store.read(peer.path)
            if not content_a or not content_b:
                continue
            claims_a = self.serializer.loads(row.path, content_a).section("Key claims")
            claims_b = self.serializer.loads(peer.path, content_b).section("Key claims")
            if not claims_a or not claims_b:
                continue
            response = await self.llm.complete_structured(
                messages=[
                    {
                        "role": "user",
                        "content": REM_CONTRADICTIONS.format(
                            path_a=row.path, claims_a=claims_a,
                            path_b=peer.path, claims_b=claims_b,
                        ),
                    }
                ],
                schema={"contradictions": []},
                operation_type="consolidate",
                prompt_name="rem_contradictions",
                **self.llm_params,
            )
            found = response.get("contradictions") or []
            for item in found:
                item["path_a"], item["path_b"] = row.path, peer.path
                contradictions.append(item)
            if found:
                await graph.upsert_edge(
                    file_ref(row.path), "contradicts", file_ref(peer.path), run_id=run.id
                )
        return contradictions

    async def _nearest_peer(self, row):
        if row.embedding is None:
            return None
        from sqlalchemy import text as sql_text

        result = await self.db.execute(
            sql_text(
                """
                SELECT path FROM context_sections
                WHERE kind = 'topic' AND status = 'active' AND pillar = :pillar
                  AND path != :path
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT 1
                """
            ),
            {"pillar": row.pillar, "path": row.path, "vec": str([float(v) for v in row.embedding])},
        )
        peer_path = result.scalar_one_or_none()
        if peer_path is None:
            return None
        return await self.db.get(ContextSections, peer_path)

    async def _render_tensions(self, contradictions: list[dict]) -> str:
        existing = await self.store.read("tensions/contradictions.md") or ""
        document = self.serializer.loads("tensions/contradictions.md", existing)
        today = datetime.now(timezone.utc).date().isoformat()
        lines = [document.body.rstrip(), "", f"## Detected {today}", ""]
        for item in contradictions:
            lines.append(
                f"- **{item.get('path_a')}** vs **{item.get('path_b')}**: "
                f"\"{item.get('claim_a', '')}\" ⟂ \"{item.get('claim_b', '')}\" — "
                f"{item.get('note', '')}"
            )
        document.body = "\n".join(lines) + "\n"
        return self.serializer.dumps(document)


def _set_gist(body: str, gist: str) -> str:
    from app.context.consolidation.light import _replace_section

    return _replace_section(body, "Gist", gist)

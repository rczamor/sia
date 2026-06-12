"""Review gate: human approval of consolidation branches.

This is the trust gate — content derived from untrusted intake only reaches main
through a human reviewing the actual diff. Approval merges, marks the linked
sources consolidated, and re-indexes; rejection deletes the branch and closes the
linked sources so they don't loop back through the light clock.
"""

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.graph import GraphService
from app.context.index import StoreIndexer
from app.context.store.documents import MarkdownSerializer
from app.context.store.gitstore import GitContextStore
from app.models.tables import ConsolidationRuns, SourceContent
from app.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class ReviewService:
    def __init__(self, db: AsyncSession, store: GitContextStore, embedder: EmbeddingProvider):
        self.db = db
        self.store = store
        self.embedder = embedder

    async def pending(self) -> list[dict]:
        branches = await self.store.list_review_branches()
        items = []
        for branch in branches:
            items.append({"branch": branch, "diff": await self.store.diff(branch)})
        return items

    async def approve(self, branch: str) -> dict:
        merge_sha = await self.store.merge_branch(branch)

        # Mark the sources behind this branch consolidated
        runs = (
            (
                await self.db.execute(
                    select(ConsolidationRuns).where(ConsolidationRuns.branch == branch)
                )
            )
            .scalars()
            .all()
        )
        source_ids = [sid for run in runs for sid in (run.input_ids or [])]
        if source_ids:
            await self.db.execute(
                update(SourceContent)
                .where(SourceContent.id.in_(source_ids))
                .values(is_consolidated=True)
            )

        # Re-index and refresh declared edges for the merged content
        indexer = StoreIndexer(self.db, self.store, self.embedder)
        indexed = await indexer.sync()
        graph = GraphService(self.db)
        serializer = MarkdownSerializer()
        for path in indexed:
            if path.startswith(("knowledge/", "skills/")):
                content = await self.store.read(path)
                if content:
                    await graph.sync_document_edges(serializer.loads(path, content), indexed)

        await self.db.commit()
        await self.store.push_mirror()
        return {"merged": branch, "sha": merge_sha, "sources_consolidated": len(source_ids)}

    async def reject(self, branch: str) -> dict:
        await self.store.delete_branch(branch)
        runs = (
            (
                await self.db.execute(
                    select(ConsolidationRuns).where(ConsolidationRuns.branch == branch)
                )
            )
            .scalars()
            .all()
        )
        source_ids = [sid for run in runs for sid in (run.input_ids or [])]
        for run in runs:
            run.status = "rejected"
        if source_ids:
            # closed, not retried — a human said no to this content
            await self.db.execute(
                update(SourceContent)
                .where(SourceContent.id.in_(source_ids))
                .values(is_consolidated=True)
            )
        await self.db.commit()
        return {"rejected": branch, "sources_closed": len(source_ids)}

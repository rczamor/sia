"""Knowledge graph: typed edges in a plain Postgres table, traversed with
recursive CTEs. No graph database.

Edge sources:
- front matter ``related:`` / ``supersedes:``  -> related_to / supersedes
- front matter ``sources:`` (data-layer UUIDs) -> derived_from
- ``[[wikilinks]]`` in bodies (Obsidian syntax) -> mentions
- consolidation clocks add supports/contradicts/requires_skill, topic->entity
  ``mentions``, and entity<->entity ``related_to`` edges whose specific relation
  phrase ("authored", "competes with", …) is carried in the edge ``label``.

Refs are namespaced strings: topic:<path>, skill:<path>, entity:<uuid>,
source:<uuid>, thought:<uuid>, artifact:<uuid>.
"""

import re
import uuid
from typing import Any

from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.store.documents import StoreDocument
from app.models.tables import ContextEdges

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")

PREDICATES = {
    "mentions",
    "supports",
    "contradicts",
    "supersedes",
    "related_to",
    "derived_from",
    "requires_skill",
}


def file_ref(document_or_path: StoreDocument | str) -> str:
    path = (
        document_or_path.path
        if isinstance(document_or_path, StoreDocument)
        else document_or_path
    )
    namespace = "skill" if path.startswith("skills/") else "topic"
    return f"{namespace}:{path}"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


class GraphService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def extract_document_edges(
        self, document: StoreDocument, known_paths: list[str]
    ) -> list[tuple[str, str, str]]:
        """Edges (subject_ref, predicate, object_ref) declared by one store file."""
        subject = file_ref(document)
        edges: list[tuple[str, str, str]] = []

        for related in document.front.get("related") or []:
            target = self._resolve(str(related), known_paths)
            if target:
                edges.append((subject, "related_to", file_ref(target)))

        supersedes = document.front.get("supersedes")
        if supersedes:
            target = self._resolve(str(supersedes), known_paths)
            if target:
                edges.append((subject, "supersedes", file_ref(target)))

        for source_id in document.front.get("sources") or []:
            try:
                edges.append((subject, "derived_from", f"source:{uuid.UUID(str(source_id))}"))
            except ValueError:
                continue

        for match in WIKILINK_RE.finditer(document.body):
            target = self._resolve(match.group(1).strip(), known_paths)
            if target and file_ref(target) != subject:
                edges.append((subject, "mentions", file_ref(target)))

        return edges

    @staticmethod
    def _resolve(reference: str, known_paths: list[str]) -> str | None:
        """Resolve a related/wikilink reference to a store path (exact path, file
        stem, or slugified title)."""
        if reference in known_paths:
            return reference
        wanted = _slug(reference)
        for path in known_paths:
            stem = path.rsplit("/", 1)[-1].removesuffix(".md")
            if stem == reference or _slug(stem) == wanted:
                return path
        return None

    async def sync_document_edges(
        self, document: StoreDocument, known_paths: list[str], run_id: uuid.UUID | None = None
    ) -> int:
        """Replace this file's declared edges with the current extraction."""
        subject = file_ref(document)
        await self.db.execute(
            delete(ContextEdges).where(
                ContextEdges.subject_ref == subject,
                ContextEdges.provenance == "declared",
            )
        )
        edges = self.extract_document_edges(document, known_paths)
        for subject_ref, predicate, object_ref in edges:
            await self.upsert_edge(
                subject_ref, predicate, object_ref, provenance="declared", run_id=run_id
            )
        return len(edges)

    async def upsert_edge(
        self,
        subject_ref: str,
        predicate: str,
        object_ref: str,
        weight: float = 1.0,
        provenance: str = "extracted",
        run_id: uuid.UUID | None = None,
        label: str | None = None,
    ) -> None:
        if predicate not in PREDICATES:
            raise ValueError(f"Unknown predicate: {predicate}")
        statement = (
            pg_insert(ContextEdges)
            .values(
                subject_ref=subject_ref,
                predicate=predicate,
                object_ref=object_ref,
                label=label,
                weight=weight,
                provenance=provenance,
                created_by_run=run_id,
            )
            .on_conflict_do_update(
                index_elements=["subject_ref", "predicate", "object_ref"],
                set_={
                    "label": label,
                    "weight": weight,
                    "provenance": provenance,
                    "created_by_run": run_id,
                },
            )
        )
        await self.db.execute(statement)

    async def neighbors(
        self, refs: list[str], depth: int = 1, predicates: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Undirected breadth-first expansion via recursive CTE; returns edges
        reachable from ``refs`` within ``depth`` hops."""
        if not refs:
            return []
        predicate_filter = "AND e.predicate = ANY(:predicates)" if predicates else ""
        # B608: predicate_filter is one of two fixed literals; values are bound.
        sql = text(
            f"""
            WITH RECURSIVE frontier AS (
                SELECT e.subject_ref, e.predicate, e.object_ref, e.weight, 1 AS hop
                FROM context_edges e
                WHERE (e.subject_ref = ANY(:refs) OR e.object_ref = ANY(:refs))
                {predicate_filter}
                UNION
                SELECT e.subject_ref, e.predicate, e.object_ref, e.weight, f.hop + 1
                FROM context_edges e
                JOIN frontier f
                  ON e.subject_ref IN (f.subject_ref, f.object_ref)
                  OR e.object_ref IN (f.subject_ref, f.object_ref)
                WHERE f.hop < :depth
                {predicate_filter}
            )
            SELECT DISTINCT subject_ref, predicate, object_ref, weight, hop FROM frontier
            """  # nosec B608
        )
        params: dict[str, Any] = {"refs": refs, "depth": depth}
        if predicates:
            params["predicates"] = predicates
        rows = await self.db.execute(sql, params)
        return [dict(row) for row in rows.mappings()]

    async def graph_snapshot(self) -> dict[str, Any]:
        """Whole-graph nodes+edges for the graph view."""
        edges = (
            await self.db.execute(
                text(
                    "SELECT subject_ref, predicate, object_ref, weight, provenance "
                    "FROM context_edges"
                )
            )
        ).mappings()
        edge_list = [dict(e) for e in edges]
        node_refs = {e["subject_ref"] for e in edge_list} | {e["object_ref"] for e in edge_list}
        return {"nodes": sorted(node_refs), "edges": edge_list}

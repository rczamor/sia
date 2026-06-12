"""Context-layer API: review gate, knowledge graph, consolidation runs."""

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.store.gitstore import REVIEW_BRANCH_PREFIX, StoreError
from app.database import get_db
from app.models.tables import ConsolidationRuns
from app.runtime import get_runtime

router = APIRouter(prefix="/api/context", tags=["context"])

BRANCH_RE = re.compile(r"^[A-Za-z0-9/_.-]+$")


def _validate_branch(branch: str) -> str:
    if not BRANCH_RE.match(branch) or not branch.startswith(REVIEW_BRANCH_PREFIX):
        raise HTTPException(status_code=400, detail="Not a review branch")
    return branch


@router.get("/review")
async def list_pending_reviews(db: AsyncSession = Depends(get_db)):
    runtime = await get_runtime()
    return await runtime.review_service(db).pending()


@router.post("/review/{branch:path}/approve")
async def approve_review(branch: str, db: AsyncSession = Depends(get_db)):
    runtime = await get_runtime()
    try:
        return await runtime.review_service(db).approve(_validate_branch(branch))
    except StoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/review/{branch:path}/reject")
async def reject_review(branch: str, db: AsyncSession = Depends(get_db)):
    runtime = await get_runtime()
    try:
        return await runtime.review_service(db).reject(_validate_branch(branch))
    except StoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/graph")
async def graph_data(db: AsyncSession = Depends(get_db)):
    """Nodes + edges for the graph view: store files, entities, and their links."""
    sections = (
        await db.execute(
            text(
                "SELECT path, kind, title, pillar, status, priority FROM context_sections "
                "WHERE kind IN ('topic', 'skill')"
            )
        )
    ).mappings()
    entities = (
        await db.execute(text("SELECT id, name, entity_type FROM entities"))
    ).mappings()
    edges = (
        await db.execute(
            text("SELECT subject_ref, predicate, object_ref, weight FROM context_edges")
        )
    ).mappings()

    nodes = {}
    for s in sections:
        ref = f"{'skill' if s['kind'] == 'skill' else 'topic'}:{s['path']}"
        nodes[ref] = {
            "id": ref,
            "label": s["title"] or s["path"],
            "kind": s["kind"],
            "pillar": s["pillar"],
            "status": s["status"],
            "priority": s["priority"],
        }
    for e in entities:
        ref = f"entity:{e['id']}"
        nodes[ref] = {
            "id": ref,
            "label": e["name"],
            "kind": "entity",
            "pillar": None,
            "status": "active",
            "priority": 0.4,
        }

    edge_list = []
    for e in edges:
        # Only render edges between known nodes (data-layer refs stay off the canvas)
        if e["subject_ref"] in nodes and e["object_ref"] in nodes:
            edge_list.append(
                {
                    "source": e["subject_ref"],
                    "target": e["object_ref"],
                    "predicate": e["predicate"],
                    "weight": e["weight"],
                }
            )
    return {"nodes": list(nodes.values()), "edges": edge_list}


@router.get("/runs")
async def list_consolidation_runs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    rows = (
        (
            await db.execute(
                select(ConsolidationRuns)
                .order_by(ConsolidationRuns.started_at.desc())
                .limit(min(limit, 200))
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(r.id),
            "clock": r.clock,
            "status": r.status,
            "branch": r.branch,
            "summary": r.summary,
            "files_changed": r.files_changed,
            "error": r.error,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
        }
        for r in rows
    ]


@router.post("/consolidate/{clock}")
async def trigger_clock(clock: str, db: AsyncSession = Depends(get_db)):
    """Manually trigger a clock (owner operation; queued, not inline)."""
    from app.jobs.tasks import deep_clock_task, light_clock_task, rem_clock_task

    tasks = {"light": light_clock_task, "rem": rem_clock_task, "deep": deep_clock_task}
    if clock not in tasks:
        raise HTTPException(status_code=404, detail=f"Unknown clock: {clock}")
    job_id = await tasks[clock].defer_async()
    return {"status": "queued", "clock": clock, "job_id": job_id}

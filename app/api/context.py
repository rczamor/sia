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
async def graph_data(
    limit: int = 500,
    pillar: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Nodes + edges for the graph view: store files, entities, and their links.
    Capped to the ``limit`` highest-priority sections (and entities) so a large
    corpus doesn't load the whole graph into one response; filterable by pillar."""
    limit = max(1, min(limit, 2000))
    pillar_clause = "AND s.pillar = :pillar" if pillar else ""
    sections = (
        await db.execute(
            text(
                f"""
                SELECT s.path, s.kind, s.title, s.pillar, s.status, s.priority,
                       coalesce(EXTRACT(EPOCH FROM (now() - s.freshness)) / 86400, 999)
                           AS age_days,
                       coalesce(u.uses, 0) AS uses
                FROM context_sections s
                LEFT JOIN (
                    SELECT item->>'path' AS path, count(*) AS uses
                    FROM context_builds, jsonb_array_elements(served) AS item
                    WHERE created_at > now() - interval '30 days'
                    GROUP BY item->>'path'
                ) u ON u.path = s.path
                WHERE s.kind IN ('topic', 'skill') {pillar_clause}
                ORDER BY s.priority DESC
                LIMIT :limit
                """
            ),
            {"limit": limit, **({"pillar": pillar} if pillar else {})},
        )
    ).mappings()
    entities = (
        await db.execute(
            text(
                "SELECT id, name, entity_type, confidence, mention_count, aliases "
                "FROM entities ORDER BY mention_count DESC, confidence DESC LIMIT :limit"
            ),
            {"limit": limit},
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
            "age_days": round(float(s["age_days"]), 1),
            "uses_30d": int(s["uses"]),
        }
    for e in entities:
        ref = f"entity:{e['id']}"
        aliases = e["aliases"] or []
        nodes[ref] = {
            "id": ref,
            "label": e["name"],
            "kind": "entity",
            "pillar": None,
            "status": "active",
            # confidence drives node size for entities, mirroring topic priority
            "priority": float(e["confidence"] or 0.4),
            "aliases": aliases,
            "mention_count": int(e["mention_count"] or 0),
            "age_days": 0,
            "uses_30d": 0,
        }

    # Fetch only edges among the capped node set (not the whole edge table).
    node_refs = list(nodes.keys())
    edges = (
        await db.execute(
            text(
                "SELECT subject_ref, predicate, object_ref, weight, label "
                "FROM context_edges "
                "WHERE subject_ref = ANY(:refs) AND object_ref = ANY(:refs)"
            ),
            {"refs": node_refs},
        )
    ).mappings()

    edge_list = []
    for e in edges:
        # Defensive: both endpoints are in the node set by the query above
        if e["subject_ref"] in nodes and e["object_ref"] in nodes:
            edge_list.append(
                {
                    "source": e["subject_ref"],
                    "target": e["object_ref"],
                    "predicate": e["predicate"],
                    "label": e["label"],  # relation phrase for entity<->entity edges
                    "weight": e["weight"],
                }
            )
    return {"nodes": list(nodes.values()), "edges": edge_list}


@router.get("/health")
async def context_health(db: AsyncSession = Depends(get_db)):
    """Context-health metrics: build quality, fallback rate, cost-per-decision,
    consolidation throughput, store freshness."""
    builds = (
        await db.execute(
            text(
                """
                SELECT count(*) AS total,
                       count(*) FILTER (WHERE created_at > now() - interval '7 days') AS last_7d,
                       coalesce(avg(context_score) FILTER (
                           WHERE created_at > now() - interval '7 days'), 0) AS avg_score_7d,
                       coalesce(avg(duration_ms) FILTER (
                           WHERE created_at > now() - interval '7 days'), 0) AS avg_duration_7d,
                       coalesce(
                           avg(CASE WHEN fallback_used THEN 1.0 ELSE 0.0 END) FILTER (
                               WHERE created_at > now() - interval '7 days'), 0
                       ) AS fallback_rate_7d,
                       count(*) FILTER (
                           WHERE flags->>'useful' = 'true'
                             AND created_at > now() - interval '7 days') AS flagged_useful_7d
                FROM context_builds
                """
            )
        )
    ).mappings().one()

    llm_cost_7d = (
        await db.execute(
            text(
                "SELECT coalesce(sum(cost_usd), 0) FROM process_lineage "
                "WHERE created_at > now() - interval '7 days'"
            )
        )
    ).scalar()

    consolidation = (
        await db.execute(
            text(
                """
                SELECT clock,
                       count(*) FILTER (WHERE started_at > now() - interval '7 days') AS runs_7d,
                       count(*) FILTER (
                           WHERE status = 'failed'
                             AND started_at > now() - interval '7 days') AS failures_7d,
                       max(started_at) AS last_run
                FROM consolidation_runs GROUP BY clock
                """
            )
        )
    ).mappings()

    store_stats = (
        await db.execute(
            text(
                """
                SELECT kind, status, count(*) AS n,
                       coalesce(avg(EXTRACT(EPOCH FROM (now() - freshness)) / 86400), 0)
                           AS avg_age_days
                FROM context_sections GROUP BY kind, status
                """
            )
        )
    ).mappings()

    builds_7d = builds["last_7d"] or 0
    return {
        "builds": {
            "total": builds["total"],
            "last_7d": builds_7d,
            "avg_context_score_7d": round(float(builds["avg_score_7d"]), 3),
            "avg_duration_ms_7d": round(float(builds["avg_duration_7d"]), 1),
            "fallback_rate_7d": round(float(builds["fallback_rate_7d"]), 3),
            "flagged_useful_7d": builds["flagged_useful_7d"],
            "cost_per_decision_7d_usd": round(float(llm_cost_7d) / builds_7d, 4)
            if builds_7d
            else None,
            "llm_cost_7d_usd": round(float(llm_cost_7d), 4),
        },
        "consolidation": [dict(row) for row in consolidation],
        "store": [dict(row) for row in store_stats],
    }


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

"""Gateway REST API: context builds (MCP parity), build audit, principal admin."""

import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tables import ContextBuilds
from app.runtime import get_runtime

router = APIRouter(tags=["gateway"])


class BuildRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=2000)
    budget_tokens: int | None = Field(default=None, ge=200, le=50000)
    pillar: str | None = None
    format: str = Field(default="json", pattern="^(json|markdown)$")


@router.post("/api/context/build")
async def build_context(
    request: Request, body: BuildRequest, db: AsyncSession = Depends(get_db)
):
    """Build a decision-ready context artifact. Authenticated principals get their
    registered budget/visibility; anonymous callers run as the visitor principal."""
    principal = request.state.principal
    runtime = await get_runtime()
    try:
        artifact = await runtime.build_context(
            db,
            goal=body.goal,
            principal=principal,
            budget_tokens=body.budget_tokens,
            pillar_hint=body.pillar,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503, detail=f"Embeddings provider unavailable: {exc}"
        )
    if body.format == "markdown":
        return {"build_id": str(artifact.build_id), "markdown": artifact.to_markdown()}
    return artifact.to_dict()


@router.get("/api/context/builds")
async def list_builds(
    request: Request, limit: int = 50, db: AsyncSession = Depends(get_db)
):
    principal = request.state.principal
    query = select(ContextBuilds).order_by(ContextBuilds.created_at.desc()).limit(min(limit, 200))
    if not principal.is_owner:
        query = query.where(ContextBuilds.principal_id == principal.id)
    rows = (await db.execute(query)).scalars().all()
    return [_build_to_dict(r) for r in rows]


@router.get("/api/context/builds/{build_id}")
async def get_build(
    request: Request, build_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    principal = request.state.principal
    row = await db.get(ContextBuilds, build_id)
    if row is None or (not principal.is_owner and row.principal_id != principal.id):
        raise HTTPException(status_code=404, detail="Unknown build")
    return _build_to_dict(row)


class FlagRequest(BaseModel):
    build_id: uuid.UUID
    useful: bool
    note: str | None = Field(default=None, max_length=500)


@router.post("/api/context/flag")
async def flag_build(request: Request, body: FlagRequest, db: AsyncSession = Depends(get_db)):
    principal = request.state.principal
    row = await db.get(ContextBuilds, body.build_id)
    if row is None or (not principal.is_owner and row.principal_id != principal.id):
        raise HTTPException(status_code=404, detail="Unknown build")
    flags = dict(row.flags or {})
    flags["useful"] = body.useful
    if body.note:
        flags["note"] = body.note
    row.flags = flags
    await db.commit()
    return {"flagged": str(body.build_id), "useful": body.useful}


class BypassRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=2000)
    source: str = Field(min_length=1, max_length=500)
    reason: str | None = Field(default=None, max_length=1000)


@router.post("/api/context/bypass", status_code=201)
async def record_bypass(request: Request, body: BypassRequest, db: AsyncSession = Depends(get_db)):
    """Record that the caller used a source outside Sia for a goal (MCP parity
    with sia_record_bypass). Feeds the bypass ledger surfaced in /api/context/health."""
    from app.models.tables import ContextBypasses

    principal = request.state.principal
    row = ContextBypasses(
        principal_id=principal.id, goal=body.goal, source=body.source, reason=body.reason
    )
    db.add(row)
    await db.commit()
    return {"recorded": str(row.id), "source": row.source}


def _build_to_dict(row: ContextBuilds) -> dict:
    return {
        "id": str(row.id),
        "principal": row.principal_id,
        "goal": row.goal,
        "pillar_hint": row.pillar_hint,
        "budget_tokens": row.budget_tokens,
        "artifact_tokens": row.artifact_tokens,
        "coverage": row.coverage,
        "context_score": row.context_score,
        "fallback_used": row.fallback_used,
        "served": row.served,
        "skills_served": row.skills_served,
        "flags": row.flags,
        "duration_ms": row.duration_ms,
        "created_at": row.created_at,
    }


# --- Principal administration (owner-only via middleware) ---


class CreateAgentRequest(BaseModel):
    purpose: str = Field(min_length=2, max_length=60, pattern="^[a-z0-9-]+$")
    token_budget: int = Field(default=8000, ge=500, le=50000)
    allowed_visibilities: list[str] = Field(default=["public"])
    allow_fallback: bool = False


@router.get("/api/principals")
async def list_principals(db: AsyncSession = Depends(get_db)):
    from app.context.principals import PrincipalService

    return await PrincipalService(db).list_all()


@router.post("/api/principals", status_code=201)
async def create_agent(body: CreateAgentRequest, db: AsyncSession = Depends(get_db)):
    from app.context.principals import PrincipalService

    try:
        principal_id, api_key = await PrincipalService(db).create_agent(
            purpose=body.purpose,
            token_budget=body.token_budget,
            allowed_visibilities=body.allowed_visibilities,
            allow_fallback=body.allow_fallback,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.commit()
    return {"principal_id": principal_id, "api_key": api_key,
            "note": "Store this key now — it is never shown again."}


@router.post("/api/principals/{principal_id}/rotate")
async def rotate_key(principal_id: str, db: AsyncSession = Depends(get_db)):
    from app.context.principals import PrincipalService

    try:
        api_key = await PrincipalService(db).rotate_key(principal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    return {"principal_id": principal_id, "api_key": api_key,
            "note": "Store this key now — it is never shown again."}


@router.delete("/api/principals/{principal_id}")
async def revoke_principal(principal_id: str, db: AsyncSession = Depends(get_db)):
    from app.context.principals import PrincipalService

    try:
        await PrincipalService(db).revoke(principal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    return {"revoked": principal_id}

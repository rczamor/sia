"""Shared clock scaffolding: run audit rows, failure alerts, zero-work detection."""

import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.tables import ConsolidationRuns

logger = logging.getLogger(__name__)

ZERO_WORK_ALERT_THRESHOLD = 3


async def start_run(db: AsyncSession, clock: str, input_ids: list[uuid.UUID] | None = None):
    run = ConsolidationRuns(clock=clock, status="running", input_ids=input_ids or [])
    db.add(run)
    await db.flush()
    return run


async def finish_run(
    db: AsyncSession,
    run,
    files_changed: list[str],
    summary: str,
    branch: str | None = None,
    cost_usd: float = 0.0,
) -> None:
    run.status = "succeeded"
    run.files_changed = files_changed
    run.summary = summary
    run.branch = branch
    run.cost_usd = cost_usd
    run.finished_at = datetime.now(timezone.utc)
    await db.flush()
    if not files_changed:
        await _check_zero_work_streak(db, run.clock)


async def fail_run(db: AsyncSession, run, error: Exception) -> None:
    run.status = "failed"
    run.error = str(error)[:2000]
    run.finished_at = datetime.now(timezone.utc)
    await db.flush()
    await send_alert(f":rotating_light: Sia {run.clock} clock failed: {error}")


async def _check_zero_work_streak(db: AsyncSession, clock: str) -> None:
    recent = (
        (
            await db.execute(
                select(ConsolidationRuns)
                .where(ConsolidationRuns.clock == clock, ConsolidationRuns.status == "succeeded")
                .order_by(ConsolidationRuns.started_at.desc())
                .limit(ZERO_WORK_ALERT_THRESHOLD)
            )
        )
        .scalars()
        .all()
    )
    if len(recent) == ZERO_WORK_ALERT_THRESHOLD and all(not r.files_changed for r in recent):
        await send_alert(
            f":zzz: Sia {clock} clock has done zero work for "
            f"{ZERO_WORK_ALERT_THRESHOLD} consecutive runs — is intake flowing?"
        )


async def send_alert(message: str) -> None:
    """Best-effort Slack webhook alert (TRZ-133). Silent no-op when unconfigured."""
    if not settings.slack_alert_webhook_url:
        logger.warning("Alert (no Slack webhook configured): %s", message)
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(settings.slack_alert_webhook_url, json={"text": message})
    except httpx.HTTPError:
        logger.exception("Failed to deliver Slack alert")

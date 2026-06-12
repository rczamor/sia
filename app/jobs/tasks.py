"""Background tasks.

Idempotency: ingest_url checks URL existence inside the task, so retries and
duplicate enqueues converge to one stored item.
"""

import logging
from datetime import datetime, timedelta, timezone

from procrastinate import RetryStrategy

from app.jobs.queue import job_queue

logger = logging.getLogger(__name__)

TRANSIENT_RETRY = RetryStrategy(max_attempts=3, exponential_wait=2)


@job_queue.task(name="ingest_url", queue="ingestion", retry=TRANSIENT_RETRY)
async def ingest_url_task(
    url: str, notes: str | None = None, pillar_override: list[str] | None = None
) -> dict:
    from app.database import async_session
    from app.runtime import get_runtime

    runtime = await get_runtime()
    async with async_session() as db:
        service = runtime.ingestion_service(db)
        result = await service.ingest_url(url=url, notes=notes, pillar_override=pillar_override)
    if "error" in result:
        # Dedup and refused URLs are terminal outcomes, not retryable failures.
        logger.info("ingest_url(%s) did not store: %s", url, result["error"])
    elif result.get("id"):
        # Post-ingest light consolidation for the new item
        await light_clock_task.defer_async(source_ids=[result["id"]])
    return result


@job_queue.task(name="light_clock", queue="consolidation", retry=TRANSIENT_RETRY)
async def light_clock_task(source_ids: list[str] | None = None) -> dict:
    import uuid as uuid_module

    from app.database import async_session
    from app.runtime import get_runtime

    runtime = await get_runtime()
    ids = [uuid_module.UUID(s) for s in source_ids] if source_ids else None
    async with async_session() as db:
        return await runtime.light_clock(db).run(ids)


@job_queue.periodic(cron="15 * * * *")
@job_queue.task(name="light_sweep", queue="consolidation")
async def light_sweep(timestamp: int | None = None) -> dict:
    """Hourly safety net: consolidate anything the post-ingest chain missed.

    Defers a real light_clock job so it runs through the queue with that task's
    retry policy, rather than executing inline within the periodic."""
    job_id = await light_clock_task.defer_async()
    return {"status": "queued", "job_id": job_id}


@job_queue.periodic(cron="0 6 * * *")
@job_queue.task(name="rem_clock", queue="consolidation")
async def rem_clock_task(timestamp: int | None = None) -> dict:
    from app.database import async_session
    from app.runtime import get_runtime

    runtime = await get_runtime()
    async with async_session() as db:
        return await runtime.rem_clock(db).run()


@job_queue.periodic(cron="0 7 * * 0")
@job_queue.task(name="deep_clock", queue="consolidation")
async def deep_clock_task(timestamp: int | None = None) -> dict:
    from app.database import async_session
    from app.runtime import get_runtime

    runtime = await get_runtime()
    async with async_session() as db:
        return await runtime.deep_clock(db).run()


@job_queue.periodic(cron="*/30 * * * *")
@job_queue.task(name="feedly_poll", queue="ingestion", retry=TRANSIENT_RETRY)
async def feedly_poll(timestamp: int | None = None) -> int:
    """Poll the configured Feedly stream and enqueue one ingest job per new item."""
    from app.models.enums import PluginCategory
    from app.runtime import get_runtime

    runtime = await get_runtime()
    feedly = runtime.plugins.get("feedly")
    if feedly is None or feedly.category != PluginCategory.INGESTION:
        logger.info("feedly plugin not enabled; skipping poll")
        return 0

    since_ms = int(
        (datetime.now(timezone.utc) - timedelta(minutes=45)).timestamp() * 1000
    )
    items = await feedly.provider.fetch_new_items(since=str(since_ms))
    enqueued = 0
    for item in items:
        await ingest_url_task.defer_async(url=item.url)
        enqueued += 1
    logger.info("feedly_poll enqueued %d items", enqueued)
    return enqueued


@job_queue.periodic(cron="0 8 * * 0")
@job_queue.task(name="autoresearch", queue="optimization")
async def autoresearch_task(timestamp: int | None = None) -> dict:
    """Weekly ratchet iteration over retrieval tunables. Opt-in: runs only when the
    autoresearch plugin row is enabled."""
    from sqlalchemy import text as sql_text

    from app.context.optimization.ratchet import TUNABLES, Ratchet
    from app.database import async_session
    from app.runtime import get_runtime

    async with async_session() as db:
        enabled = (
            await db.execute(
                sql_text("SELECT enabled FROM plugins WHERE id = 'autoresearch'")
            )
        ).scalar()
        if not enabled:
            logger.info("autoresearch disabled; skipping")
            return {"skipped": True}

        runtime = await get_runtime()
        ratchet = Ratchet(db, runtime.context_store, runtime.embedder)
        results = {}
        for parameter in TUNABLES:
            outcome = await ratchet.iterate(parameter)
            results[parameter] = {
                "promoted": outcome.promoted,
                "value": outcome.candidate if outcome.promoted else outcome.incumbent,
                "score": outcome.candidate_score,
            }
        logger.info("autoresearch iteration: %s", results)
        return results

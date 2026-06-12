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
    return result


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

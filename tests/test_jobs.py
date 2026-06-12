"""Job-queue tests: durable enqueue, idempotent ingestion, periodic Feedly polling."""

import pytest
from procrastinate import testing

from app.jobs.queue import job_queue
from app.jobs.tasks import feedly_poll, ingest_url_task


@pytest.fixture
def memory_queue():
    connector = testing.InMemoryConnector()
    with job_queue.replace_connector(connector):
        yield connector


async def test_ingest_url_endpoint_enqueues_job(client, memory_queue):
    response = await client.post(
        "/api/ingest/url", json={"url": "https://93.184.216.34/some-article"}
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    jobs = list(memory_queue.jobs.values())
    assert len(jobs) == 1
    assert jobs[0]["task_name"] == "ingest_url"
    assert jobs[0]["args"]["url"] == "https://93.184.216.34/some-article"


async def test_jobs_survive_in_postgres(db_session):
    """Durability: a deferred job is a Postgres row — worker restarts lose nothing."""
    from sqlalchemy import text

    async with job_queue.open_async():
        await ingest_url_task.defer_async(url="https://93.184.216.34/durable")

    row = (
        await db_session.execute(
            text("SELECT task_name, args, status FROM procrastinate_jobs ORDER BY id DESC")
        )
    ).first()
    assert row is not None
    assert row.task_name == "ingest_url"
    assert row.args["url"] == "https://93.184.216.34/durable"
    assert row.status == "todo"


async def test_ingest_url_task_is_idempotent(db_session, monkeypatch, memory_queue):
    """Re-running the same URL job converges: the second run is a no-op dedup."""
    from sqlalchemy import text

    from app.data.ingestion import IngestionService
    from app.data.lineage import LineageService, TrackedLLMProvider
    from tests.fakes import FakeEmbedding, FakeLLM

    class FakeRuntime:
        def ingestion_service(self, db):
            service = IngestionService(
                db, TrackedLLMProvider(FakeLLM(), LineageService(db)), FakeEmbedding()
            )

            async def fake_fetch(url):
                return "<html><body><p>" + "Context is generated, not retrieved. " * 30 + "</p></body></html>"

            monkeypatch.setattr("app.data.ingestion.fetch_public_url", fake_fetch)
            return service

    async def fake_get_runtime():
        return FakeRuntime()

    monkeypatch.setattr("app.runtime.get_runtime", fake_get_runtime)

    result_one = await ingest_url_task(url="https://93.184.216.34/idempotent")
    result_two = await ingest_url_task(url="https://93.184.216.34/idempotent")

    assert "error" not in result_one
    assert "already exists" in result_two["error"]
    count = (
        await db_session.execute(text("SELECT count(*) FROM source_content"))
    ).scalar()
    assert count == 1


async def test_feedly_poll_enqueues_per_item(memory_queue, monkeypatch):
    from app.models.enums import PluginCategory
    from app.providers.base import RawContent

    class FakeFeedly:
        category = PluginCategory.INGESTION
        provider = property(lambda self: self)

        async def fetch_new_items(self, since=None):
            return [
                RawContent(title="A", url="https://example.com/a", content=""),
                RawContent(title="B", url="https://example.com/b", content=""),
            ]

    class FakeRuntime:
        class plugins:
            @staticmethod
            def get(plugin_id):
                return FakeFeedly() if plugin_id == "feedly" else None

    async def fake_get_runtime():
        return FakeRuntime()

    monkeypatch.setattr("app.runtime.get_runtime", fake_get_runtime)

    enqueued = await feedly_poll()
    assert enqueued == 2
    urls = [j["args"]["url"] for j in memory_queue.jobs.values() if j["task_name"] == "ingest_url"]
    assert urls == ["https://example.com/a", "https://example.com/b"]


async def test_light_sweep_defers_rather_than_runs_inline(memory_queue):
    """The hourly sweep must enqueue a light_clock job (queue+retry semantics),
    not execute the clock inline."""
    from app.jobs.tasks import light_sweep

    result = await light_sweep()
    assert result["status"] == "queued"
    tasks = [j["task_name"] for j in memory_queue.jobs.values()]
    assert "light_clock" in tasks

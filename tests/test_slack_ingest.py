"""Slack capture-channel webhook: auth, URL extraction, thought storage."""

import pytest
from procrastinate import testing

from app.config import settings
from app.jobs.queue import job_queue


@pytest.fixture
def memory_queue():
    connector = testing.InMemoryConnector()
    with job_queue.replace_connector(connector):
        yield connector


@pytest.fixture
def slack_secret(monkeypatch):
    monkeypatch.setattr(settings, "slack_webhook_secret", "test-slack-secret")
    return "test-slack-secret"


async def test_rejects_missing_or_wrong_token(client, slack_secret):
    response = await client.post("/api/ingest/slack", json={"text": "hello"})
    assert response.status_code == 401
    response = await client.post(
        "/api/ingest/slack",
        json={"text": "hello"},
        headers={"X-Sia-Slack-Token": "wrong"},
    )
    assert response.status_code == 401


async def test_unconfigured_returns_503(client):
    response = await client.post(
        "/api/ingest/slack", json={"text": "x"}, headers={"X-Sia-Slack-Token": "x"}
    )
    assert response.status_code == 503


async def test_queues_urls_and_stores_thought(client, slack_secret, memory_queue, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.data.ingestion import IngestionService
    from app.data.lineage import LineageService, TrackedLLMProvider
    from tests.fakes import FakeEmbedding, FakeLLM

    async def fake_service(db: AsyncSession) -> IngestionService:
        return IngestionService(
            db, TrackedLLMProvider(FakeLLM(), LineageService(db)), FakeEmbedding()
        )

    monkeypatch.setattr("app.api.ingest._get_ingestion_service", fake_service)

    response = await client.post(
        "/api/ingest/slack",
        json={"text": "worth reading https://93.184.216.34/paper — this supports the thesis about consolidation"},
        headers={"X-Sia-Slack-Token": slack_secret},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["urls_queued"] == 1
    assert body["thought_id"] is not None
    urls = [j["args"]["url"] for j in memory_queue.jobs.values() if j["task_name"] == "ingest_url"]
    assert urls == ["https://93.184.216.34/paper"]


async def test_internal_urls_are_dropped(client, slack_secret, memory_queue):
    response = await client.post(
        "/api/ingest/slack",
        json={"text": "http://169.254.169.254/latest/meta-data/"},
        headers={"X-Sia-Slack-Token": slack_secret},
    )
    assert response.status_code == 202
    assert response.json()["urls_queued"] == 0

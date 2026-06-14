"""Generic ingestion webhook: auth, content vs. url routing, SSRF guard."""

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
def webhook_secret(monkeypatch):
    monkeypatch.setattr(settings, "ingest_webhook_secret", "test-webhook-secret")
    return "test-webhook-secret"


def _tasks(memory_queue, name):
    return [j for j in memory_queue.jobs.values() if j["task_name"] == name]


async def test_unconfigured_returns_503(client):
    response = await client.post(
        "/api/ingest/webhook",
        json={"title": "x", "content": "y"},
        headers={"X-Sia-Webhook-Token": "x"},
    )
    assert response.status_code == 503


async def test_rejects_missing_or_wrong_token(client, webhook_secret):
    response = await client.post("/api/ingest/webhook", json={"title": "x", "content": "y"})
    assert response.status_code == 401
    response = await client.post(
        "/api/ingest/webhook",
        json={"title": "x", "content": "y"},
        headers={"X-Sia-Webhook-Token": "wrong"},
    )
    assert response.status_code == 401


async def test_content_queues_ingest_content(client, webhook_secret, memory_queue):
    response = await client.post(
        "/api/ingest/webhook",
        json={"title": "Q3 doc", "content": "the full text", "source": "zapier:gdrive"},
        headers={"X-Sia-Webhook-Token": webhook_secret},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["mode"] == "content"

    jobs = _tasks(memory_queue, "ingest_content")
    assert len(jobs) == 1
    args = jobs[0]["args"]
    assert args["title"] == "Q3 doc"
    assert args["content"] == "the full text"
    assert args["notes"] == "via zapier:gdrive"
    assert not _tasks(memory_queue, "ingest_url")


async def test_url_only_queues_ingest_url(client, webhook_secret, memory_queue):
    response = await client.post(
        "/api/ingest/webhook",
        json={"title": "A paper", "url": "https://93.184.216.34/paper"},
        headers={"X-Sia-Webhook-Token": webhook_secret},
    )
    assert response.status_code == 202
    assert response.json()["mode"] == "url"
    urls = [j["args"]["url"] for j in _tasks(memory_queue, "ingest_url")]
    assert urls == ["https://93.184.216.34/paper"]


async def test_internal_url_is_refused(client, webhook_secret, memory_queue):
    response = await client.post(
        "/api/ingest/webhook",
        json={"title": "ssrf", "url": "http://169.254.169.254/latest/meta-data/"},
        headers={"X-Sia-Webhook-Token": webhook_secret},
    )
    assert response.status_code == 400
    assert not _tasks(memory_queue, "ingest_url")


async def test_requires_content_or_url(client, webhook_secret):
    response = await client.post(
        "/api/ingest/webhook",
        json={"title": "empty"},
        headers={"X-Sia-Webhook-Token": webhook_secret},
    )
    assert response.status_code == 400

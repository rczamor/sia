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


async def test_url_mode_stays_untrusted_even_with_source(client, webhook_secret, memory_queue):
    """A caller-supplied `source` becomes a provenance note, but must NOT elevate
    webhook intake from untrusted to curated (notes-implies-curated is owner-only)."""
    response = await client.post(
        "/api/ingest/webhook",
        json={"title": "A paper", "url": "https://93.184.216.34/paper", "source": "zapier:rss"},
        headers={"X-Sia-Webhook-Token": webhook_secret},
    )
    assert response.status_code == 202
    job = _tasks(memory_queue, "ingest_url")[0]
    assert job["args"]["trust_tier"] == "untrusted"
    assert job["args"]["notes"] == "via zapier:rss"


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


async def test_non_http_url_is_rejected(client, webhook_secret, memory_queue):
    response = await client.post(
        "/api/ingest/webhook",
        json={"title": "x", "content": "y", "url": "javascript:alert(1)"},
        headers={"X-Sia-Webhook-Token": webhook_secret},
    )
    assert response.status_code == 422
    assert not _tasks(memory_queue, "ingest_content")


async def test_non_ascii_token_is_401_not_500(client, webhook_secret):
    """An attacker can put raw bytes 0x80-0xFF in the header; Starlette decodes them
    latin-1 into a non-ASCII str. compare_digest on plain str would raise (→500), so
    the token must be compared as bytes. Sent as raw bytes because an HTTP client
    can't transmit a non-ASCII *str* header value."""
    response = await client.post(
        "/api/ingest/webhook",
        json={"title": "x", "content": "y"},
        headers={"X-Sia-Webhook-Token": "tökén".encode("latin-1")},
    )
    assert response.status_code == 401

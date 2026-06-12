import pytest

from app.data.url_safety import UnsafeURLError, assert_safe_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "gopher://example.com",
        "http://",
    ],
)
def test_rejects_bad_schemes_and_missing_hosts(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:8000/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        "http://10.0.0.5/internal",
        "http://192.168.1.1/router",
        "http://[::1]/",
        "http://0.0.0.0/",
    ],
)
def test_rejects_private_and_metadata_addresses(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


def test_accepts_public_address():
    # IP literal avoids DNS dependence in tests; 93.184.216.34 is example.com.
    assert_safe_url("https://93.184.216.34/article")


async def test_ingest_url_endpoint_refuses_internal_targets(client):
    # The endpoint validates before anything is enqueued — no job, no fetch.
    response = await client.post(
        "/api/ingest/url", json={"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert response.status_code == 400
    assert "URL refused" in response.json()["detail"]

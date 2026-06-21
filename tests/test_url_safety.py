import pytest

from app.data.url_safety import (
    PublicOnlyAsyncNetworkBackend,
    UnsafeURLError,
    assert_safe_url,
)


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


async def test_connection_backend_pins_verified_ip(monkeypatch):
    """The actual TCP connect uses the validated IP, not the original hostname."""
    import socket

    class CapturingBackend:
        def __init__(self):
            self.connected_host = None

        async def connect_tcp(self, host, port, **kwargs):
            self.connected_host = host
            return object()

        async def connect_unix_socket(self, *args, **kwargs):
            raise AssertionError("not used")

        async def sleep(self, seconds):
            pass

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )

    capture = CapturingBackend()
    backend = PublicOnlyAsyncNetworkBackend(capture)
    await backend.connect_tcp("example.com", 443)
    assert capture.connected_host == "93.184.216.34"


async def test_connection_backend_rejects_rebound_private_ip(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.10", 80))
        ],
    )

    backend = PublicOnlyAsyncNetworkBackend()
    with pytest.raises(UnsafeURLError):
        await backend.connect_tcp("example.com", 80)


async def test_ingest_url_endpoint_refuses_internal_targets(client):
    # The endpoint validates before anything is enqueued — no job, no fetch.
    response = await client.post(
        "/api/ingest/url", json={"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert response.status_code == 400
    assert "URL refused" in response.json()["detail"]


async def test_fetch_aborts_on_oversize_stream(monkeypatch):
    """A streamed body exceeding the cap is aborted without buffering it all."""
    import httpx

    from app.data import url_safety

    monkeypatch.setattr(url_safety, "assert_safe_url", lambda url: None)
    monkeypatch.setattr(url_safety, "MAX_CONTENT_BYTES", 1000)

    big = b"x" * 5000

    def handler(request):
        return httpx.Response(200, content=big)

    real_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs.pop("follow_redirects", None)
        return real_client(*args, follow_redirects=False, **kwargs)

    monkeypatch.setattr(url_safety.httpx, "AsyncClient", make_client)

    with pytest.raises(url_safety.UnsafeURLError) as exc:
        await url_safety.fetch_public_url("https://93.184.216.34/big")
    assert "exceeds" in str(exc.value)


async def test_fetch_rejects_oversize_content_length(monkeypatch):
    import httpx

    from app.data import url_safety

    monkeypatch.setattr(url_safety, "assert_safe_url", lambda url: None)
    monkeypatch.setattr(url_safety, "MAX_CONTENT_BYTES", 1000)

    def handler(request):
        return httpx.Response(200, headers={"content-length": "999999"}, content=b"hi")

    real_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs.pop("follow_redirects", None)
        return real_client(*args, follow_redirects=False, **kwargs)

    monkeypatch.setattr(url_safety.httpx, "AsyncClient", make_client)

    with pytest.raises(url_safety.UnsafeURLError):
        await url_safety.fetch_public_url("https://93.184.216.34/big")

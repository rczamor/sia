"""SSRF-safe URL fetching for ingestion.

Ingestion accepts arbitrary URLs from operators, so every fetch must be prevented
from reaching internal networks or cloud metadata endpoints (169.254.169.254 et al.).
Redirects are validated per hop rather than trusting the first URL. The HTTP
transport also resolves and validates the host at connection time, then opens the
TCP socket to that verified IP while preserving the original hostname for HTTP and
TLS certificate validation. That closes the usual DNS-rebinding gap between
preflight validation and network use.
"""

import asyncio
import ipaddress
import socket
import ssl
from typing import Any, Iterable
from urllib.parse import urlparse

import httpcore
import httpx

ALLOWED_SCHEMES = {"http", "https"}
MAX_CONTENT_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
FETCH_TIMEOUT_SECONDS = 20.0
USER_AGENT = "Sia/0.1 (context engine ingestion)"
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
DEFAULT_LIMITS = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
    keepalive_expiry=5.0,
)


class UnsafeURLError(ValueError):
    """Raised when a URL must not be fetched (scheme, host, or size policy)."""


def _resolve_public_ips_sync(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host: {host}") from exc
    ips: list[str] = []
    for info in infos:
        ip_text = info[4][0]
        ip = ipaddress.ip_address(ip_text)
        if not ip.is_global:
            raise UnsafeURLError(f"Host resolves to a non-public address: {host}")
        if ip_text not in ips:
            ips.append(ip_text)
    if not ips:
        raise UnsafeURLError(f"Could not resolve host: {host}")
    return ips


async def _resolve_public_ips(host: str) -> list[str]:
    return await asyncio.to_thread(_resolve_public_ips_sync, host)


def _assert_public_host(host: str) -> None:
    _resolve_public_ips_sync(host)


def assert_safe_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"URL scheme not allowed: {parsed.scheme or '(none)'}")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no host")
    _assert_public_host(parsed.hostname)


class PublicOnlyAsyncNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolve once, validate, then connect to the verified IP address.

    httpcore still uses the request origin hostname for the Host header, SNI, and
    certificate verification after this TCP socket is opened.
    """

    def __init__(
        self,
        backend: httpcore.AsyncNetworkBackend | None = None,
    ):
        from httpcore._backends.auto import AutoBackend

        self._backend = backend or AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[tuple[int, int, int | bytes]] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        last_error: Exception | None = None
        for resolved_ip in await _resolve_public_ips(host):
            try:
                return await self._backend.connect_tcp(
                    resolved_ip,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise UnsafeURLError(f"Could not resolve host: {host}")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[tuple[int, int, int | bytes]] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self._backend.connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options
        )

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class PublicOnlyAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """HTTPX transport with connection-time public-IP pinning."""

    def __init__(
        self,
        verify: ssl.SSLContext | str | bool = True,
        cert: Any = None,
        trust_env: bool = True,
        limits: httpx.Limits | None = None,
    ):
        limits = limits or DEFAULT_LIMITS
        super().__init__(verify=verify, cert=cert, trust_env=trust_env, limits=limits)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(
                verify=verify, cert=cert, trust_env=trust_env
            ),
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            network_backend=PublicOnlyAsyncNetworkBackend(),
        )


async def fetch_public_url(url: str) -> str:
    """Fetch a public URL, re-validating the target on every redirect hop and
    aborting as soon as the streamed body exceeds the size cap — so a malicious
    endpoint can't force large memory use by sending a huge response."""
    current = url
    async with httpx.AsyncClient(
        transport=PublicOnlyAsyncHTTPTransport(trust_env=False),
        follow_redirects=False,
        timeout=FETCH_TIMEOUT_SECONDS,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            assert_safe_url(current)
            async with client.stream("GET", current) as response:
                if response.status_code in REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise UnsafeURLError("Redirect response without Location header")
                    current = str(httpx.URL(current).join(location))
                    continue
                response.raise_for_status()

                # Reject early on an advertised oversize Content-Length.
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > MAX_CONTENT_BYTES:
                    raise UnsafeURLError(
                        f"Response exceeds {MAX_CONTENT_BYTES} bytes; refusing to ingest"
                    )

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_CONTENT_BYTES:
                        raise UnsafeURLError(
                            f"Response exceeds {MAX_CONTENT_BYTES} bytes; refusing to ingest"
                        )
                    chunks.append(chunk)
                body = b"".join(chunks)
                encoding = response.encoding or "utf-8"
                return body.decode(encoding, errors="replace")
    raise UnsafeURLError(f"Too many redirects (>{MAX_REDIRECTS})")

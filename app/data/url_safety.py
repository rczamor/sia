"""SSRF-safe URL fetching for ingestion.

Ingestion accepts arbitrary URLs from operators, so every fetch must be prevented
from reaching internal networks or cloud metadata endpoints (169.254.169.254 et al.).
Redirects are validated per hop rather than trusting the first URL.

Known residual risk: DNS rebinding between the resolve-check and the connect is not
mitigated here (would require pinning resolved IPs into the transport). Tracked in
the threat model.
"""

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

ALLOWED_SCHEMES = {"http", "https"}
MAX_CONTENT_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
FETCH_TIMEOUT_SECONDS = 20.0
USER_AGENT = "Sia/0.1 (context engine ingestion)"
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class UnsafeURLError(ValueError):
    """Raised when a URL must not be fetched (scheme, host, or size policy)."""


def _assert_public_host(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise UnsafeURLError(f"Host resolves to a non-public address: {host}")


def assert_safe_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"URL scheme not allowed: {parsed.scheme or '(none)'}")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no host")
    _assert_public_host(parsed.hostname)


async def fetch_public_url(url: str) -> str:
    """Fetch a public URL, re-validating the target on every redirect hop and
    aborting as soon as the streamed body exceeds the size cap — so a malicious
    endpoint can't force large memory use by sending a huge response."""
    current = url
    async with httpx.AsyncClient(
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

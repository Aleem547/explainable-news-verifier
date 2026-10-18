"""Phase 13C.2: fail-closed HTTPS fetcher for an explicitly approved publisher.

No article URL is fetched merely because a discovery provider mentioned it.
The caller must separately determine publisher permissions/robots policy and
provide a trusted, server-side allowlist. Public HTML is still NOT verified evidence.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from apps.api.connectors.contracts import ContentKind, ExternalDiscoveryHit
from ml.ingestion.validation import validated_discovery_identity
from ml.provenance.identity import normalize_source_domain


class ArticleFetchError(ValueError):
    """Safe failure code; no untrusted URL or response text in error messages."""


@dataclass(frozen=True, slots=True)
class ArticleFetchPolicy:
    max_html_bytes: int = 1_000_000
    timeout_seconds: float = 5.0
    max_total_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not 1024 <= self.max_html_bytes <= 2_000_000:
            raise ValueError("Invalid HTML byte limit")
        if not 1.0 <= self.timeout_seconds <= 15.0:
            raise ValueError("Invalid socket timeout")
        if not self.timeout_seconds <= self.max_total_seconds <= 60.0:
            raise ValueError("Invalid total timeout")


@dataclass(frozen=True, slots=True)
class FetchedArticleHtml:
    fetched_url: str
    html_body: bytes
    content_type: str
    retrieved_at: datetime
    # This is fetched external content, NOT independently verified evidence.
    independently_verified: bool = False


def _resolve_public_ipv4(hostname: str) -> str:
    """Check *all* DNS answers, then pick one public IPv4 to pin the TCP peer.

    Mixed public/private DNS answers are rejected, rather than silently using
    the public address. IPv6-only hosts fail closed in this initial version.
    """
    try:
        records = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise ArticleFetchError("dns_resolution_failed") from exc
    if not records or len(records) > 32:
        raise ArticleFetchError("invalid_dns_answers")

    ipv4: list[str] = []
    for family, _, _, _, sockaddr in records:
        if family not in (socket.AF_INET, socket.AF_INET6):
            raise ArticleFetchError("unsupported_dns_answer")
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise ArticleFetchError("invalid_dns_answer") from exc
        if not address.is_global:
            raise ArticleFetchError("nonpublic_dns_answer")
        if isinstance(address, ipaddress.IPv4Address):
            ipv4.append(str(address))
    if not ipv4:
        raise ArticleFetchError("no_public_ipv4_answer")
    return ipv4[0]


class _PinnedHttpsConnection(http.client.HTTPSConnection):
    """Connect to the vetted numeric IP, but authenticate the original DNS name."""

    def __init__(self, hostname: str, vetted_ip: str, timeout: float):
        super().__init__(hostname, 443, timeout=timeout, context=ssl.create_default_context())
        self._vetted_ip = vetted_ip

    def connect(self) -> None:
        raw = socket.create_connection((self._vetted_ip, 443), timeout=self.timeout)
        try:
            # TLS SNI AND certificate hostname verification both use self.host.
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _read_response(connection: _PinnedHttpsConnection, limit: int, deadline: float) -> bytes:
    response = connection.getresponse()
    if 300 <= response.status <= 399:
        # Redirect targets must be revalidated and pinned; not supported yet.
        raise ArticleFetchError("redirect_refused")
    if response.status != 200:
        raise ArticleFetchError("http_error")
    content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "text/html":
        raise ArticleFetchError("unsupported_content_type")
    if response.getheader("Content-Encoding", "identity").lower() != "identity":
        # Refuse compressed streams rather than risking decompression bombs.
        raise ArticleFetchError("compressed_response_refused")
    length = response.getheader("Content-Length")
    if length is not None:
        try:
            declared_length = int(length)
        except ValueError as exc:
            raise ArticleFetchError("invalid_content_length") from exc
        if declared_length < 0 or declared_length > limit:
            raise ArticleFetchError("payload_too_large")

    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ArticleFetchError("fetch_timeout")
        # Recheck total deadline before each bounded read.
        if connection.sock is not None:
            connection.sock.settimeout(min(remaining, connection.timeout))
        piece = response.read(min(16_384, limit + 1 - total))
        if not piece:
            break
        total += len(piece)
        if total > limit:
            raise ArticleFetchError("payload_too_large")
        chunks.append(piece)
    if not chunks:
        raise ArticleFetchError("empty_response")
    return b"".join(chunks)


def fetch_discovered_article_html(
    *,
    discovery_hit: ExternalDiscoveryHit,
    approved_publisher_domains: frozenset[str] = frozenset(),
    policy: ArticleFetchPolicy | None = None,
) -> FetchedArticleHtml:
    """Fetch one allowed public HTTPS article with DNS-pin and TLS hostname checks.

    Synchronous/blocking: run via asyncio.to_thread in an async route/worker.
    The `approved_publisher_domains` MUST come from trusted server configuration
    after publisher/robots permission checks, never directly from user input.
    """
    settings = policy or ArticleFetchPolicy()
    if discovery_hit.kind is not ContentKind.NEWS_ARTICLE:
        raise ArticleFetchError("not_a_news_article")
    try:
        url, domain = validated_discovery_identity(discovery_hit)
        approved = frozenset(normalize_source_domain(item) for item in approved_publisher_domains)
        parsed = urlsplit(url)
        hostname = normalize_source_domain(parsed.hostname or "")
    except (ValueError, UnicodeError) as exc:
        raise ArticleFetchError("invalid_article_identity") from exc
    if domain not in approved:
        raise ArticleFetchError("publisher_not_approved")
    if parsed.scheme != "https" or parsed.port not in (None, 443):
        raise ArticleFetchError("insecure_scheme_or_port")

    # DNS validation must occur immediately before the IP-pinned connection.
    vetted_ip = _resolve_public_ipv4(hostname)
    deadline = time.monotonic() + settings.max_total_seconds
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    conn = _PinnedHttpsConnection(hostname, vetted_ip, settings.timeout_seconds)
    try:
        conn.request(
            "GET", path,
            headers={
                "Host": hostname,
                "Accept": "text/html",
                "Accept-Encoding": "identity",
                "User-Agent": "ExplainableNewsVerifier/0.1 (+authorized-article-fetch)",
                "Connection": "close",
            },
        )
        body = _read_response(conn, settings.max_html_bytes, deadline)
    except ArticleFetchError:
        raise
    except (OSError, ssl.SSLError, http.client.HTTPException, TimeoutError, UnicodeError) as exc:
        raise ArticleFetchError("network_error") from exc
    finally:
        conn.close()

    return FetchedArticleHtml(
        fetched_url=url,
        html_body=body,
        content_type="text/html",
        retrieved_at=datetime.now(timezone.utc),
    )

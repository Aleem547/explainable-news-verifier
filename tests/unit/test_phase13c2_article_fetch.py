"""Offline-only tests: never contact article websites."""

import socket
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from apps.api.connectors.contracts import ContentKind, ExternalDiscoveryHit, Provider
from apps.api.services.article_fetch import (
    ArticleFetchError,
    ArticleFetchPolicy,
    _PinnedHttpsConnection,
    _read_response,
    _resolve_public_ipv4,
    fetch_discovered_article_html,
)

MODULE = "apps.api.services.article_fetch"


def hit(url="https://news.example.org/story", domain="news.example.org"):
    return ExternalDiscoveryHit(
        provider=Provider.RSS_FEED,
        kind=ContentKind.NEWS_ARTICLE,
        url=url,
        publisher_domain=domain,
        publisher_name="Example News",
        title="A factual headline",
        snippet=None,
        discovered_at=datetime.now(timezone.utc),
        published_at=None,
    )


class ArticleFetcherTests(unittest.TestCase):
    def records(self, *ips):
        return [
            (socket.AF_INET6 if ":" in ip else socket.AF_INET,
             socket.SOCK_STREAM, 6, "", (ip, 443))
            for ip in ips
        ]

    def test_allows_one_public_ipv4(self):
        with patch(f"{MODULE}.socket.getaddrinfo", return_value=self.records("8.8.8.8")):
            self.assertEqual(_resolve_public_ipv4("news.example.org"), "8.8.8.8")

    def test_rejects_private_ipv4(self):
        with patch(f"{MODULE}.socket.getaddrinfo", return_value=self.records("127.0.0.1")):
            with self.assertRaisesRegex(ArticleFetchError, "nonpublic_dns_answer"):
                _resolve_public_ipv4("news.example.org")

    def test_rejects_cloud_metadata_ipv4(self):
        with patch(f"{MODULE}.socket.getaddrinfo", return_value=self.records("169.254.169.254")):
            with self.assertRaisesRegex(ArticleFetchError, "nonpublic_dns_answer"):
                _resolve_public_ipv4("news.example.org")

    def test_rejects_mixed_public_private(self):
        with patch(f"{MODULE}.socket.getaddrinfo", return_value=self.records("8.8.8.8", "10.0.0.1")):
            with self.assertRaisesRegex(ArticleFetchError, "nonpublic_dns_answer"):
                _resolve_public_ipv4("news.example.org")

    def test_rejects_ipv6_loopback(self):
        with patch(f"{MODULE}.socket.getaddrinfo", return_value=self.records("::1", "8.8.8.8")):
            with self.assertRaisesRegex(ArticleFetchError, "nonpublic_dns_answer"):
                _resolve_public_ipv4("news.example.org")

    def test_rejects_dns_failure(self):
        with patch(f"{MODULE}.socket.getaddrinfo", side_effect=socket.gaierror("dns")):
            with self.assertRaisesRegex(ArticleFetchError, "dns_resolution_failed"):
                _resolve_public_ipv4("news.example.org")

    def test_rejects_ipv6_only(self):
        with patch(f"{MODULE}.socket.getaddrinfo", return_value=self.records("2606:4700:4700::1111")):
            with self.assertRaisesRegex(ArticleFetchError, "no_public_ipv4_answer"):
                _resolve_public_ipv4("news.example.org")

    def test_rejects_more_than_32_answers(self):
        with patch(f"{MODULE}.socket.getaddrinfo", return_value=self.records(*(["8.8.8.8"] * 33))):
            with self.assertRaisesRegex(ArticleFetchError, "invalid_dns_answers"):
                _resolve_public_ipv4("news.example.org")

    def test_unapproved_source_never_resolves(self):
        with patch(f"{MODULE}._resolve_public_ipv4") as dns:
            with self.assertRaisesRegex(ArticleFetchError, "publisher_not_approved"):
                fetch_discovered_article_html(discovery_hit=hit())
            dns.assert_not_called()

    def test_refuses_http_url(self):
        with self.assertRaises(ArticleFetchError):
            fetch_discovered_article_html(discovery_hit=hit(url="http://news.example.org/story"),
                approved_publisher_domains=frozenset({"news.example.org"}))

    def test_refuses_publisher_mismatch(self):
        with self.assertRaises(ArticleFetchError):
            fetch_discovered_article_html(discovery_hit=hit(domain="other.example.org"),
                approved_publisher_domains=frozenset({"other.example.org"}))

    def test_refuses_nonstandard_port(self):
        with self.assertRaisesRegex(ArticleFetchError, "insecure_scheme_or_port"):
            fetch_discovered_article_html(discovery_hit=hit(url="https://news.example.org:444/story"),
                approved_publisher_domains=frozenset({"news.example.org"}))

    def test_refuses_redirect(self):
        response = MagicMock(status=302)
        response.getheader.return_value = "text/html"
        conn = MagicMock()
        conn.getresponse.return_value = response
        with self.assertRaisesRegex(ArticleFetchError, "redirect_refused"):
            _read_response(conn, 1024, float("inf"))

    def test_refuses_oversized_content_length(self):
        response = MagicMock(status=200)
        response.getheader.side_effect = lambda name, default=None: {
            "Content-Type": "text/html", "Content-Length": "999999999"
        }.get(name, default)
        conn = MagicMock()
        conn.getresponse.return_value = response
        with self.assertRaisesRegex(ArticleFetchError, "payload_too_large"):
            _read_response(conn, 2048, float("inf"))

    def test_refuses_compressed_response(self):
        response = MagicMock(status=200)
        response.getheader.side_effect = lambda name, default=None: {
            "Content-Type": "text/html", "Content-Encoding": "gzip"
        }.get(name, default)
        conn = MagicMock()
        conn.getresponse.return_value = response
        with self.assertRaisesRegex(ArticleFetchError, "compressed_response_refused"):
            _read_response(conn, 2048, float("inf"))

    def test_happy_path_pins_ip_and_returns_unverified_html(self):
        response = MagicMock(status=200)
        response.getheader.side_effect = lambda name, default=None: {
            "Content-Type": "text/html", "Content-Length": "17"
        }.get(name, default)
        response.read.side_effect = [b"<html>body</html>", b""]
        conn = MagicMock(sock=None, timeout=5.0)
        conn.getresponse.return_value = response
        with (patch(f"{MODULE}._resolve_public_ipv4", return_value="8.8.8.8"),
              patch(f"{MODULE}._PinnedHttpsConnection", return_value=conn) as cls):
            result = fetch_discovered_article_html(discovery_hit=hit(),
                approved_publisher_domains=frozenset({"news.example.org"}))
        cls.assert_called_once_with("news.example.org", "8.8.8.8", 5.0)
        self.assertEqual(result.html_body, b"<html>body</html>")
        self.assertFalse(result.independently_verified)
        conn.close.assert_called_once()

    def test_pinned_connection_tls_hostname(self):
        fake_raw = MagicMock()
        fake_wrapped = MagicMock()
        conn = _PinnedHttpsConnection("news.example.org", "8.8.8.8", 5.0)
        fake_context = MagicMock()
        fake_context.wrap_socket.return_value = fake_wrapped
        conn._context = fake_context
        with patch(f"{MODULE}.socket.create_connection", return_value=fake_raw) as create:
            conn.connect()
        create.assert_called_once_with(("8.8.8.8", 443), timeout=5.0)
        fake_context.wrap_socket.assert_called_once_with(fake_raw, server_hostname="news.example.org")
        self.assertIs(conn.sock, fake_wrapped)

    def test_policy_bounds(self):
        with self.assertRaises(ValueError):
            ArticleFetchPolicy(max_html_bytes=50)
        with self.assertRaises(ValueError):
            ArticleFetchPolicy(timeout_seconds=0.1)
        with self.assertRaises(ValueError):
            ArticleFetchPolicy(timeout_seconds=5, max_total_seconds=3)

    def test_refuses_non_html(self):
        response = MagicMock(status=200)
        response.getheader.side_effect = lambda name, default=None: {
            "Content-Type": "application/pdf"
        }.get(name, default)
        conn = MagicMock()
        conn.getresponse.return_value = response
        with self.assertRaisesRegex(ArticleFetchError, "unsupported_content_type"):
            _read_response(conn, 2048, float("inf"))

    def test_refuses_large_stream_even_without_content_length(self):
        response = MagicMock(status=200)
        response.getheader.side_effect = lambda name, default=None: {
            "Content-Type": "text/html"
        }.get(name, default)
        response.read.side_effect = [b"a" * 1024, b"b" * 1024, b"c"]
        conn = MagicMock(sock=None, timeout=5.0)
        conn.getresponse.return_value = response
        with self.assertRaisesRegex(ArticleFetchError, "payload_too_large"):
            _read_response(conn, 2048, float("inf"))

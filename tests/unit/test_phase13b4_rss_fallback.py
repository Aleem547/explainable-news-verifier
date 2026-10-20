"""Offline safety and orchestration tests: no real news requests or database writes."""

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

import httpx

from apps.api.connectors.contracts import DiscoveryRequest, DiscoveryResult, Provider
from apps.api.connectors.http_client import ConnectorError, HttpPolicy, ProviderHttpClient
from apps.api.connectors.rss import RSS_FEEDS, RssFeedConnector, parse_rss_items
from apps.api.schemas.multisource import ExternalDiscoveryRequest
from apps.api.connectors.fallback import discover_gdelt_or_rss


def sample_rss(*, link="https://www.bbc.com/news/articles/1234", title="Eiffel Tower in Paris"):
    return (f'''<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>News</title>
      <item><title>{title}</title><description>Details about Paris and Eiffel Tower</description>
      <link>{link}</link><pubDate>Sun, 18 Oct 2026 12:30:00 GMT</pubDate></item>
    </channel></rss>''').encode()


class RssFallbackTests(unittest.IsolatedAsyncioTestCase):
    def test_accepts_relevant_allowlisted_article(self):
        hits = parse_rss_items(sample_rss(), RSS_FEEDS[0],
                               DiscoveryRequest("Eiffel Tower located in Paris"), datetime.now(UTC))
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].publisher_name, "BBC News")
        self.assertEqual(hits[0].published_at.year, 2026)
        self.assertIsNone(hits[0].snippet)
        self.assertEqual(hits[0].provider, Provider.RSS_FEED)

    def test_rejects_foreign_domain_in_trusted_feed(self):
        hits = parse_rss_items(sample_rss(link="https://malicious.example/story"),
                               RSS_FEEDS[0], DiscoveryRequest("Eiffel Paris"), datetime.now(UTC))
        self.assertFalse(hits)

    def test_unrelated_headline_is_not_matched(self):
        hits = parse_rss_items(sample_rss(title="Another story").replace(
             b"Details about Paris and Eiffel Tower", b"Unrelated summary"),
             RSS_FEEDS[0], DiscoveryRequest("Eiffel Tower"), datetime.now(UTC))
        self.assertEqual(hits, ())

    def test_rejects_entities_and_doctype(self):
        sample = b'<!DOCTYPE rss [<!ENTITY boom "overload">]><rss><channel/></rss>'
        with self.assertRaises(ConnectorError) as err:
            parse_rss_items(sample, RSS_FEEDS[0], DiscoveryRequest("Paris"), datetime.now(UTC))
        self.assertEqual(err.exception.reason, "unsafe_xml")

    def test_rejects_non_rss(self):
        with self.assertRaises(ConnectorError) as err:
            parse_rss_items(b'<html><body>Hello</body></html>', RSS_FEEDS[0],
                            DiscoveryRequest("Paris"), datetime.now(UTC))
        self.assertEqual(err.exception.reason, "unsupported_feed_format")

    async def test_rss_connector_uses_fixed_endpoints(self):
        visited = []
        def handler(req):
            visited.append(str(req.url))
            if req.url.host == "feeds.bbci.co.uk":
                return httpx.Response(200, content=sample_rss(), headers={"content-type":"application/rss+xml"})
            return httpx.Response(503)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            result = await RssFeedConnector(ProviderHttpClient(c)).search(DiscoveryRequest("Eiffel Tower", limit=5))
        self.assertEqual(len(visited), len(RSS_FEEDS))
        self.assertEqual(set(visited), {feed.url for feed in RSS_FEEDS})
        self.assertEqual(result.provider, Provider.RSS_FEED)
        self.assertEqual(len(result.hits), 1)

    async def test_rss_rejects_redirects_and_html(self):
        for response, expected in [
            (httpx.Response(302, headers={"location":"http://localhost"}), "redirect_refused"),
            (httpx.Response(200, text="<html/>", headers={"content-type":"text/html"}), "unexpected_content_type"),
        ]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as c:
                with self.assertRaises(ConnectorError) as err:
                    await ProviderHttpClient(c).get_feed_xml(provider="rss_feed", endpoint=RSS_FEEDS[0].url)
                self.assertEqual(err.exception.reason, expected)

    async def test_rss_limits_bytes(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x" * 1200,
                                     headers={"content-type":"application/rss+xml"}))) as c:
            with self.assertRaises(ConnectorError) as err:
                await ProviderHttpClient(c, HttpPolicy(max_bytes=1000)).get_feed_xml(
                    provider="rss_feed", endpoint=RSS_FEEDS[0].url)
            self.assertEqual(err.exception.reason, "payload_too_large")

    async def test_never_fetch_arbitrary_feed(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
             lambda _: self.fail("Unexpected network"))) as c:
            with self.assertRaises(ValueError):
                await ProviderHttpClient(c).get_feed_xml(
                    provider="rss_feed", endpoint="https://127.0.0.1/rss.xml")

    async def test_all_feeds_failed(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
             lambda _: httpx.Response(429))) as c:
            with self.assertRaises(ConnectorError) as err:
                await RssFeedConnector(ProviderHttpClient(c)).search(DiscoveryRequest("Eiffel Tower"))
            self.assertEqual(err.exception.reason, "all_feeds_failed")

    async def test_transient_gdelt_error_triggers_rss_fallback(self):
        class FakeGdelt:
            def __init__(self, _http):
                pass
            async def search(self, _request):
                raise ConnectorError("gdelt_doc", "retry_exhausted_http_429")
        class FakeRss:
            def __init__(self, _http):
                pass
            async def search(self, request):
                return DiscoveryResult(provider=Provider.RSS_FEED, query=request.query, hits=())
        with patch('apps.api.connectors.fallback.GdeltDocConnector', FakeGdelt), \
             patch('apps.api.connectors.fallback.RssFeedConnector', FakeRss):
            result, did_fallback = await discover_gdelt_or_rss(
                None, DiscoveryRequest("Eiffel Tower"))
        self.assertTrue(did_fallback)
        self.assertEqual(result.provider, Provider.RSS_FEED)
        self.assertEqual(len(result.hits), 0)

    async def test_bad_gdelt_response_does_not_trigger_fallback(self):
        class FakeGdelt:
            def __init__(self, _http):
                pass
            async def search(self, _request):
                raise ConnectorError("gdelt_doc", "invalid_article_list")
        with patch('apps.api.connectors.fallback.GdeltDocConnector', FakeGdelt), \
             patch('apps.api.connectors.fallback.RssFeedConnector') as mock_rss:
            with self.assertRaises(ConnectorError):
                await discover_gdelt_or_rss(None, DiscoveryRequest("Eiffel Tower"))
            mock_rss.assert_not_called()

    def test_existing_provider_default_unchanged(self):
        self.assertEqual(ExternalDiscoveryRequest(query="Paris").provider, "both")
        self.assertEqual(ExternalDiscoveryRequest(query="Paris", provider="rss").provider, "rss")


if __name__ == '__main__':
    unittest.main()

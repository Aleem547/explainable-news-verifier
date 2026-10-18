"""Offline tests for Phase 13B.2 using mocked HTTP transport."""

import unittest
import json
import httpx

from apps.api.connectors.contracts import DiscoveryRequest, Provider
from apps.api.connectors.gdelt import GdeltDocConnector
from apps.api.connectors.http_client import ConnectorError, HttpPolicy, ProviderHttpClient
from apps.api.schemas.multisource import ExternalDiscoveryRequest


class GdeltHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_host_and_metadata_only(self):
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"articles": [
                {"url": "https://news.example.org/post", "title": "A report",
                 "language": "English", "seendate": "20261018T120000Z"},
                {"url": "https://news.example.org/post", "title": "Duplicated"},
                {"url": "http://bad.example.org/post", "title": "Insecure"},
                {"url": "https://foreign.example.org/post", "title": "Spanish", "language": "Spanish"},
            ]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await GdeltDocConnector(ProviderHttpClient(client)).search(
                DiscoveryRequest(query="Eiffel Tower in Paris", limit=5))
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].url.host, "api.gdeltproject.org")
        self.assertEqual(seen[0].url.path, "/api/v2/doc/doc")
        self.assertEqual(seen[0].url.params["mode"], "artlist")
        self.assertEqual(seen[0].url.params["maxrecords"], "5")
        self.assertEqual(result.provider, Provider.GDELT_DOC)
        self.assertEqual(len(result.hits), 1)
        hit = result.hits[0]
        self.assertEqual(hit.provider, Provider.GDELT_DOC)
        self.assertEqual(hit.url, "https://news.example.org/post")
        self.assertEqual(hit.publisher_domain, "news.example.org")
        self.assertEqual(hit.language, "en")
        self.assertIsNone(hit.published_at)
        self.assertIsNone(hit.snippet)
        self.assertIsNotNone(hit.discovered_at.utcoffset())

    async def test_empty_response_does_not_imply_false_claim(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"articles": []}))) as client:
            result = await GdeltDocConnector(ProviderHttpClient(client)).search(
                DiscoveryRequest(query="Eiffel Tower Paris"))
        self.assertEqual(result.hits, ())
        self.assertIsNone(result.reported_total)
        self.assertIn("not article full text", result.warning)

    async def test_malformed_article_list(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"wrong": True}))) as client:
            with self.assertRaises(ConnectorError) as err:
                await GdeltDocConnector(ProviderHttpClient(client)).search(
                    DiscoveryRequest(query="Eiffel Tower Paris"))
        self.assertEqual(err.exception.reason, "invalid_article_list")

    async def test_external_redirect_refused(self):
        count = 0
        def handler(_):
            nonlocal count
            count += 1
            return httpx.Response(302, headers={"Location": "http://127.0.0.1"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ConnectorError) as err:
                await GdeltDocConnector(ProviderHttpClient(client)).search(
                    DiscoveryRequest(query="Eiffel Tower Paris"))
        self.assertEqual(err.exception.reason, "redirect_refused")
        self.assertEqual(count, 1)

    async def test_response_size_bounded(self):
        body = json.dumps({"articles": [], "padding": "x" * 3000})
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _: httpx.Response(200, text=body))) as client:
            with self.assertRaises(ConnectorError) as err:
                await GdeltDocConnector(ProviderHttpClient(client, HttpPolicy(max_bytes=1000))).search(
                    DiscoveryRequest(query="Eiffel Tower Paris"))
        self.assertEqual(err.exception.reason, "payload_too_large")

    async def test_retry_limit_on_rate_limit(self):
        calls = 0
        def handler(_):
            nonlocal calls
            calls += 1
            return httpx.Response(429)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ConnectorError) as err:
                await GdeltDocConnector(ProviderHttpClient(client, HttpPolicy(
                    max_attempts=2, backoff_seconds=0))).search(
                    DiscoveryRequest(query="Eiffel Tower Paris"))
        self.assertEqual(calls, 2)
        self.assertEqual(err.exception.reason, "retry_exhausted_http_429")

    async def test_language_rejected_without_network(self):
        count = 0
        def handler(_):
            nonlocal count
            count += 1
            return httpx.Response(200, json={"articles": []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ValueError):
                await GdeltDocConnector(ProviderHttpClient(client)).search(
                    DiscoveryRequest(query="Some query", language="de"))
        self.assertEqual(count, 0)

    def test_request_schema_explicit_gdelt(self):
        self.assertEqual(ExternalDiscoveryRequest(query="Eiffel Tower", provider="gdelt").provider, "gdelt")
        self.assertEqual(ExternalDiscoveryRequest(query="Eiffel Tower").provider, "both")


if __name__ == "__main__":
    unittest.main()

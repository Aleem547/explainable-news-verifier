"""Phase 13E.2: real local Trafilatura with synthetic HTML, never HTTP."""

from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone

from apps.api.connectors.contracts import ContentKind, ExternalDiscoveryHit, Provider
from apps.api.services.article_fetch import FetchedArticleHtml
from apps.api.services.article_url_preparation import prepare_discovered_article_url
from ml.provenance.identity import sha256_text

_URL = "https://news.example.org/a-story"
_TEXT = (
    "The town council met on Tuesday to review proposed changes to the city park. "
    "The meeting lasted two hours and included discussion of pedestrian safety. "
    "Residents shared feedback regarding accessible pathways and public transport. "
    "A follow-up hearing was scheduled for the next month, according to the statement. "
)
_HTML = ("<!doctype html><html lang='en'><head><title>Town council discusses park</title></head>"
         "<body><main><article><h1>Town council discusses park</h1>"
         "<p>" + _TEXT + "</p><p>" + _TEXT + "</p></article></main></body></html>").encode("utf-8")


class RealExtractorOfflineSmoke(unittest.IsolatedAsyncioTestCase):
    async def test_fetched_synthetic_article_is_extracted_without_network(self):
        if importlib.util.find_spec("trafilatura") is None:
            self.fail("Trafilatura is required to run the optional real-extractor smoke test")
        stamp = datetime.now(timezone.utc)
        hit = ExternalDiscoveryHit(
            provider=Provider.RSS_FEED, kind=ContentKind.NEWS_ARTICLE,
            url=_URL, publisher_domain="news.example.org", publisher_name="Example News",
            title="Town council discusses park", snippet=None,
            discovered_at=stamp, published_at=None,
        )
        calls = []
        def synthetic_fetcher(**kwargs):
            calls.append("mock_fetch")
            return FetchedArticleHtml(fetched_url=_URL, html_body=_HTML,
                                      content_type="text/html", retrieved_at=stamp)

        result = await prepare_discovered_article_url(
            submitted_url=_URL, approved_discovery_hit=hit,
            approved_publisher_domains=frozenset({"news.example.org"}),
            publisher_access_approved=True, fetcher=synthetic_fetcher,
        )
        self.assertEqual(calls, ["mock_fetch"])
        self.assertEqual(result.canonical_url, _URL)
        self.assertGreater(len(result.article.text), 100)
        self.assertEqual(result.article.text_sha256, sha256_text(result.article.text))
        self.assertFalse(result.independently_verified)
        self.assertFalse(result.article.independently_verified)


if __name__ == "__main__":
    unittest.main()

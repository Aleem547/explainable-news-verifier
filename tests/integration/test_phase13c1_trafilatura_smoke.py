"""Real local Trafilatura smoke test. Network, database and cloud are never accessed."""

import importlib.util
import unittest
from datetime import UTC, datetime

from apps.api.connectors.contracts import ContentKind, ExternalDiscoveryHit, Provider
from apps.api.services.article_extraction import extract_discovered_article_html

URL = "https://www.theguardian.com/world/synthetic-article"
NOW = datetime(2026, 10, 19, tzinfo=UTC)
PARAGRAPH = (
    "Investigators published a comprehensive report about a public announcement. "
    "The statement included specific dates, institutional context, and a discussion "
    "of how officials expected the process to proceed following the announcement. "
)
HTML = (
    "<html><head><title>A sample report about a public announcement</title>"
    '<meta name="author" content="Sample Reporter"></head>'
    '<body><main><article><h1>A sample report about a public announcement</h1>'
    + "".join("<p>" + PARAGRAPH + "</p>" for _ in range(5))
    + "</article></main></body></html>"
).encode("utf-8")


@unittest.skipUnless(importlib.util.find_spec("trafilatura"), "Install trafilatura locally")
class RealTrafilaturaSmoke(unittest.TestCase):
    def test_extracts_synthetic_page_without_network(self):
        hit = ExternalDiscoveryHit(
            provider=Provider.RSS_FEED,
            kind=ContentKind.NEWS_ARTICLE,
            url=URL,
            publisher_domain="www.theguardian.com",
            publisher_name="The Guardian",
            title="A sample report",
            snippet=None,
            discovered_at=NOW,
            published_at=None,
        )
        result = extract_discovered_article_html(
            discovery_hit=hit,
            fetched_url=URL,
            html_body=HTML,
            retrieved_at=NOW,
            content_type="text/html; charset=utf-8",
        )
        self.assertIn("Investigators published", result.text)
        self.assertTrue(result.text_sha256)
        self.assertFalse(result.independently_verified)


if __name__ == "__main__":
    unittest.main()

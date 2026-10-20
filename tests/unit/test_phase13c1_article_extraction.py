"""Offline tests: no network, database, or trafilatura install needed."""

import json
import unittest
from datetime import UTC, datetime
from hashlib import sha256

from apps.api.connectors.contracts import ContentKind, ExternalDiscoveryHit, Provider
from apps.api.services.article_extraction import (
    ArticleExtractionError,
    ArticleExtractionPolicy,
    extract_discovered_article_html,
)
from ml.provenance.identity import sha256_text


ARTICLE = "A clearly attributable news article describes the circumstances of the public " \
          "announcement, explains the official response, and provides additional context. " \
          "The published text includes a detailed account of the relevant events."
BODY = b"<html><head><title>Public news</title></head><body><article>demo</article></body></html>"
WHEN = datetime(2026, 10, 19, tzinfo=UTC)


def hit(url="https://www.theguardian.com/world/example", *, kind=ContentKind.NEWS_ARTICLE):
    return ExternalDiscoveryHit(
        provider=Provider.RSS_FEED,
        kind=kind,
        url=url,
        publisher_domain="www.theguardian.com",
        publisher_name="The Guardian",
        title="Public news",
        snippet=None,
        discovered_at=WHEN,
        published_at=None,
    )


def fake_extract(_html, **_kwargs):
    return json.dumps({
        "text": ARTICLE, "title": "  Report   title  ",
        "author": "  Reporter Name ", "date": "2026-10-18",
        "url": "https://evil.example/article", "source": "fake publisher",
    })


class ArticleExtractionTests(unittest.TestCase):
    def call(self, **kwargs):
        base = dict(discovery_hit=hit(), fetched_url=hit().url,
                    html_body=BODY, retrieved_at=WHEN, extractor=fake_extract)
        base.update(kwargs)
        return extract_discovered_article_html(**base)

    def expect_reason(self, reason, **kwargs):
        with self.assertRaises(ArticleExtractionError) as ctx:
            self.call(**kwargs)
        self.assertEqual(str(ctx.exception), reason)

    def test_extraction_has_attributable_hashes_and_unverified_flag(self):
        result = self.call()
        self.assertEqual(result.document_url, hit().url)
        self.assertEqual(result.publisher_domain, hit().publisher_domain)
        self.assertEqual(result.text, ARTICLE)
        self.assertEqual(result.text_sha256, sha256_text(ARTICLE))
        self.assertEqual(result.html_sha256, sha256(BODY).hexdigest())
        self.assertFalse(result.independently_verified)
        self.assertEqual(result.extraction_method, "trafilatura_json_v1")

    def test_title_author_date_are_advisory(self):
        result = self.call()
        self.assertEqual(result.title, "Report title")
        self.assertEqual(result.author, "Reporter Name")
        self.assertEqual(result.reported_publication_date, "2026-10-18")

    def test_html_embedded_url_cannot_replace_discovery_identity(self):
        self.assertEqual(self.call().document_url, hit().url)

    def test_refuse_changed_redirect_destination(self):
        self.expect_reason("article_url_mismatch", fetched_url="https://www.theguardian.com/other")

    def test_refuse_http(self):
        self.expect_reason(
            "invalid_article_identity",
            discovery_hit=hit("http://www.theguardian.com/world/example"),
            fetched_url="http://www.theguardian.com/world/example",
        )

    def test_refuse_nonstandard_port(self):
        self.expect_reason("insecure_article_scheme_or_port", discovery_hit=hit(
            "https://www.theguardian.com:8443/world/example"),
            fetched_url="https://www.theguardian.com:8443/world/example")

    def test_refuse_other_host(self):
        self.expect_reason("invalid_article_identity", fetched_url="https://localhost/private")

    def test_refuse_fact_check_kind(self):
        self.expect_reason(
            "not_a_news_article", discovery_hit=hit(kind=ContentKind.FACT_CHECK_REVIEW)
        )

    def test_refuse_naive_timestamp(self):
        self.expect_reason("naive_retrieval_timestamp", retrieved_at=datetime(2026, 10, 19))

    def test_refuse_large_body(self):
        self.expect_reason("html_response_size_outside_limit", html_body=b"a" * 1_000_001)

    def test_refuse_bad_content_type(self):
        self.expect_reason("unsupported_content_type", content_type="application/pdf")

    def test_refuse_unparseable_json(self):
        self.expect_reason("invalid_extraction_json", extractor=lambda *_args, **_kwargs: "no")

    def test_refuse_empty_extraction(self):
        self.expect_reason("article_text_not_found", extractor=lambda *_args, **_kwargs: None)

    def test_refuse_too_short_extraction(self):
        self.expect_reason(
            "article_text_size_outside_limit",
            extractor=lambda *_args, **_kwargs: '{"text":"short"}',
        )

    def test_validate_policy(self):
        with self.assertRaises(ValueError):
            ArticleExtractionPolicy(max_html_bytes=300)

    def test_extraction_does_not_fetch(self):
        recorded = {}
        def injected(html, **kwargs):
            recorded.update(kwargs)
            self.assertEqual(html, BODY)
            return json.dumps({"text": ARTICLE})
        self.call(extractor=injected)
        self.assertEqual(recorded["url"], hit().url)
        self.assertFalse(recorded["include_comments"])
        self.assertEqual(recorded["output_format"], "json")


if __name__ == "__main__":
    unittest.main()

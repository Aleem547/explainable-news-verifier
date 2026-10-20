"""Offline tests for Phase 13E.2. No network, database or model inference."""

from __future__ import annotations

import asyncio
import hashlib
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from apps.api.connectors.contracts import ContentKind, ExternalDiscoveryHit, Provider
from apps.api.services.article_extraction import ArticleExtractionPolicy, ExtractedArticle
from apps.api.services.article_fetch import ArticleFetchPolicy, FetchedArticleHtml
from apps.api.services.article_url_preparation import (
    ArticleUrlPreparationError,
    PreparedArticleUrl,
    _canonical_input,
    prepare_discovered_article_url,
)
from ml.provenance.identity import sha256_text

URL = "https://news.example.org/coverage?edition=1"
DOMAIN = "news.example.org"
TEXT = ("Carefully reviewed article text. " * 10).strip()
HTML = b"<html><body>Carefully reviewed article text.</body></html>"
NOW = datetime.now(timezone.utc)


def make_hit(**changes) -> ExternalDiscoveryHit:
    values = dict(provider=Provider.RSS_FEED, kind=ContentKind.NEWS_ARTICLE,
                  url=URL, publisher_domain=DOMAIN, publisher_name="Example News",
                  title="News article", snippet=None, discovered_at=NOW, published_at=None)
    values.update(changes)
    return ExternalDiscoveryHit(**values)


def make_fetched(**changes) -> FetchedArticleHtml:
    return replace(FetchedArticleHtml(fetched_url=URL, html_body=HTML,
                                      content_type="text/html", retrieved_at=NOW), **changes)


def make_article(**changes) -> ExtractedArticle:
    return replace(ExtractedArticle(
        document_url=URL, publisher_domain=DOMAIN, publisher_name="Example News",
        text=TEXT, text_sha256=sha256_text(TEXT), html_sha256=hashlib.sha256(HTML).hexdigest(),
        title="News article", author=None, reported_publication_date=None,
        retrieved_at=NOW,
    ), **changes)


class UrlInputTests(unittest.TestCase):
    def test_plain_https_url(self):
        self.assertEqual(_canonical_input(URL), URL)

    def test_explicit_default_port(self):
        self.assertEqual(_canonical_input("https://news.example.org:443/coverage?edition=1"), URL)

    def test_fragment_is_not_used_as_identity(self):
        self.assertEqual(_canonical_input(URL + "#heading"), URL)

    def test_refuses_http(self):
        with self.assertRaisesRegex(ArticleUrlPreparationError, "invalid_submitted_url"):
            _canonical_input("http://news.example.org/coverage")

    def test_refuses_localhost(self):
        with self.assertRaises(ArticleUrlPreparationError):
            _canonical_input("https://localhost/private")

    def test_refuses_ip_literal(self):
        with self.assertRaises(ArticleUrlPreparationError):
            _canonical_input("https://169.254.169.254/latest/")

    def test_refuses_url_credentials(self):
        with self.assertRaises(ArticleUrlPreparationError):
            _canonical_input("https://u:p@news.example.org/coverage")

    def test_refuses_nonstandard_https_port(self):
        with self.assertRaises(ArticleUrlPreparationError):
            _canonical_input("https://news.example.org:8443/coverage")

    def test_refuses_nonurl(self):
        with self.assertRaises(ArticleUrlPreparationError):
            _canonical_input(None)  # type: ignore[arg-type]

    def test_refuses_oversized_url(self):
        with self.assertRaises(ArticleUrlPreparationError):
            _canonical_input(URL + "a" * 3000)

    def test_refuses_control_chars_and_whitespace(self):
        for value in (" " + URL, URL + "\r\n", URL + "\t"):
            with self.subTest(value=value), self.assertRaises(ArticleUrlPreparationError):
                _canonical_input(value)


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def run_pipeline(self, *, hit=None, fetched=None, article=None, url=URL,
                           approved=True, domains=None, **extra):
        fetcher = Mock(return_value=make_fetched() if fetched is None else fetched)
        extractor = Mock(return_value=make_article() if article is None else article)
        settings = dict(submitted_url=url, approved_discovery_hit=make_hit() if hit is None else hit,
                        approved_publisher_domains=frozenset({DOMAIN}) if domains is None else domains,
                        publisher_access_approved=approved, fetcher=fetcher, extractor=extractor)
        settings.update(extra)
        try:
            outcome = await prepare_discovered_article_url(**settings)
        except ArticleUrlPreparationError as error:
            return error, fetcher, extractor
        return outcome, fetcher, extractor

    async def assert_refused(self, code: str, **kwargs):
        outcome, fetcher, extractor = await self.run_pipeline(**kwargs)
        self.assertIsInstance(outcome, ArticleUrlPreparationError)
        self.assertEqual(str(outcome), code)
        return fetcher, extractor

    async def test_success_preserves_url_and_unverified_content(self):
        outcome, fetcher, extractor = await self.run_pipeline()
        self.assertIsInstance(outcome, PreparedArticleUrl)
        self.assertEqual(outcome.canonical_url, URL)
        self.assertEqual(outcome.publisher_name, "Example News")
        self.assertEqual(outcome.state, "READY_FOR_CLAIM_EXTRACTION")
        self.assertFalse(outcome.independently_verified)
        self.assertFalse(outcome.article.independently_verified)
        self.assertEqual(outcome.article.text_sha256, sha256_text(TEXT))
        fetcher.assert_called_once()
        self.assertEqual(fetcher.call_args.kwargs["approved_publisher_domains"], frozenset({DOMAIN}))
        extractor.assert_called_once()

    async def test_canonical_default_https_port_matches_trusted_discovery(self):
        result, *_ = await self.run_pipeline(url="https://news.example.org:443/coverage?edition=1")
        self.assertIsInstance(result, PreparedArticleUrl)

    async def test_missing_explicit_permission_blocks_fetch(self):
        fetch, extract = await self.assert_refused("publisher_access_not_approved", approved=False)
        fetch.assert_not_called(); extract.assert_not_called()

    async def test_unapproved_domain_blocks_fetch(self):
        fetch, extract = await self.assert_refused("publisher_not_approved", domains=frozenset({"other.example.org"}))
        fetch.assert_not_called(); extract.assert_not_called()

    async def test_forged_discovery_identity_blocks_fetch(self):
        fetch, extract = await self.assert_refused("invalid_discovery_identity", hit=make_hit(publisher_domain="other.example.org"))
        fetch.assert_not_called(); extract.assert_not_called()

    async def test_wrong_url_blocks_fetch(self):
        fetch, extract = await self.assert_refused("url_not_equal_to_trusted_discovery", url="https://news.example.org/unexpected")
        fetch.assert_not_called(); extract.assert_not_called()

    async def test_different_query_blocks_fetch(self):
        fetch, extract = await self.assert_refused("url_not_equal_to_trusted_discovery", url="https://news.example.org/coverage?edition=2")
        fetch.assert_not_called(); extract.assert_not_called()

    async def test_requires_news_article_not_fact_check(self):
        fetch, extract = await self.assert_refused("not_a_news_article", hit=make_hit(kind=ContentKind.FACT_CHECK_REVIEW))
        fetch.assert_not_called(); extract.assert_not_called()

    async def test_rejects_untrusted_hit_object(self):
        fetch, extract = await self.assert_refused("trusted_discovery_hit_required", hit=object())
        fetch.assert_not_called(); extract.assert_not_called()

    async def test_invalid_allowlist_fails_closed(self):
        fetch, extract = await self.assert_refused("invalid_publisher_allowlist", domains=frozenset({"https://news.example.org"}))
        fetch.assert_not_called(); extract.assert_not_called()

    async def test_incompatible_size_limits_block_fetch(self):
        fetch, extract = await self.assert_refused(
            "incompatible_html_size_limits", fetch_policy=ArticleFetchPolicy(max_html_bytes=1_500_000),
            extraction_policy=ArticleExtractionPolicy(max_html_bytes=1_000_000),
        )
        fetch.assert_not_called(); extract.assert_not_called()

    async def test_fetched_identity_mismatch_rejected_before_extraction(self):
        _, extract = await self.assert_refused("fetched_url_mismatch", fetched=make_fetched(fetched_url="https://news.example.org/elsewhere"))
        extract.assert_not_called()

    async def test_fetched_verified_flag_rejected(self):
        await self.assert_refused("unexpected_verified_content", fetched=make_fetched(independently_verified=True))

    async def test_wrong_fetch_result_type_rejected(self):
        _, extract = await self.assert_refused("invalid_fetch_result", fetched="<html>unsafe</html>")
        extract.assert_not_called()

    async def test_invalid_fetch_content_type_rejected(self):
        await self.assert_refused("unexpected_content_type", fetched=make_fetched(content_type="application/pdf"))

    async def test_large_html_rejected(self):
        await self.assert_refused("invalid_html_body", fetched=make_fetched(html_body=b"X" * 1_000_001))

    async def test_future_fetch_time_rejected(self):
        await self.assert_refused("future_fetch_timestamp", fetched=make_fetched(retrieved_at=NOW + timedelta(days=1)))

    async def test_naive_fetch_time_rejected(self):
        await self.assert_refused("invalid_fetch_timestamp", fetched=make_fetched(retrieved_at=datetime.now()))

    async def test_extract_identity_mismatch_rejected(self):
        await self.assert_refused("extraction_identity_mismatch", article=make_article(publisher_name="Attacker"))

    async def test_extract_verified_flag_rejected(self):
        await self.assert_refused("unexpected_verified_content", article=make_article(independently_verified=True))

    async def test_extraction_timestamp_mismatch_rejected(self):
        await self.assert_refused("extraction_timestamp_mismatch", article=make_article(retrieved_at=NOW - timedelta(seconds=10)))

    async def test_extracted_text_hash_mismatch_rejected(self):
        await self.assert_refused("extracted_text_hash_mismatch", article=make_article(text_sha256="0" * 64))

    async def test_extracted_html_hash_mismatch_rejected(self):
        await self.assert_refused("extracted_html_hash_mismatch", article=make_article(html_sha256="0" * 64))

    async def test_extracted_text_bounds_rejected(self):
        await self.assert_refused("extracted_text_invalid", article=make_article(text="tiny"))

    async def test_wrong_extracted_content_type_rejected(self):
        await self.assert_refused("invalid_extraction_content_type", article=make_article(content_type="text/plain"))

    async def test_fetch_error_sanitized(self):
        def bad_fetch(**kwargs):
            raise RuntimeError("secrets from remote response")
        with self.assertRaisesRegex(ArticleUrlPreparationError, "^approved_article_fetch_failed$"):
            await prepare_discovered_article_url(
                submitted_url=URL, approved_discovery_hit=make_hit(),
                approved_publisher_domains=frozenset({DOMAIN}), publisher_access_approved=True,
                fetcher=bad_fetch,
            )

    async def test_extraction_error_sanitized(self):
        def bad_extract(**kwargs):
            raise RuntimeError("secret response")
        with self.assertRaisesRegex(ArticleUrlPreparationError, "^article_extraction_failed$"):
            await prepare_discovered_article_url(
                submitted_url=URL, approved_discovery_hit=make_hit(),
                approved_publisher_domains=frozenset({DOMAIN}), publisher_access_approved=True,
                fetcher=lambda **kw: make_fetched(), extractor=bad_extract,
            )

    async def test_fetched_before_extractor(self):
        events = []
        def fetcher(**kw):
            events.append("fetch")
            return make_fetched()
        def extractor(**kw):
            events.append("extract")
            return make_article()
        result = await prepare_discovered_article_url(
            submitted_url=URL, approved_discovery_hit=make_hit(),
            approved_publisher_domains=frozenset({DOMAIN}), publisher_access_approved=True,
            fetcher=fetcher, extractor=extractor,
        )
        self.assertIsInstance(result, PreparedArticleUrl)
        self.assertEqual(events, ["fetch", "extract"])


if __name__ == "__main__":
    unittest.main()

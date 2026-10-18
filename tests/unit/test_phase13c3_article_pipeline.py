"""Offline tests: no network, PostgreSQL, or publisher content required."""

import asyncio
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from apps.api.connectors.contracts import (
    ContentKind, DiscoveryResult, ExternalDiscoveryHit, Provider,
)
from apps.api.services.article_extraction import ExtractedArticle
from apps.api.services.article_fetch import FetchedArticleHtml
from apps.api.services.article_content_pipeline import (
    ArticlePipelineError, fetch_extract_store_authorized_article,
    store_authorized_article,
)
from ml.provenance.identity import sha256_text

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
URL = "https://www.bbc.com/news/articles/test-independent-article"
TEXT = "This is a synthetic article for offline verification tests. " * 5
HTML = ("<html><body><article><p>" + TEXT + "</p></article></body></html>").encode()


def fixture():
    hit = ExternalDiscoveryHit(
        provider=Provider.RSS_FEED, kind=ContentKind.NEWS_ARTICLE,
        url=URL, publisher_domain="www.bbc.com", publisher_name="BBC News",
        title="Synthetic article", snippet=None, discovered_at=NOW, published_at=NOW,
    )
    result = DiscoveryResult(provider=Provider.RSS_FEED, query="synthetic", hits=(hit,))
    article = ExtractedArticle(
        document_url=URL, publisher_domain="www.bbc.com", publisher_name="BBC News",
        text=TEXT, text_sha256=sha256_text(TEXT), html_sha256=sha256(HTML).hexdigest(),
        title="Synthetic article", author=None, reported_publication_date="2026-10-18",
        retrieved_at=NOW,
    )
    return result, article


class StubSession:
    def __init__(self):
        self.savepoint_started = False
        self.observation = SimpleNamespace(metadata_json=None)
        self.get = AsyncMock(return_value=self.observation)
        self.flush = AsyncMock()

    def begin_nested(self):
        parent = self

        class Savepoint:
            async def __aenter__(self):
                parent.savepoint_started = True

            async def __aexit__(self, *_):
                return False

        return Savepoint()


class ArticlePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_refuses_unauthorized_storage_before_db(self):
        result, article = fixture()
        session = StubSession()
        with self.assertRaisesRegex(ArticlePipelineError, "storage_not_authorized"):
            await store_authorized_article(session, discovery_result=result, article=article)
        self.assertFalse(session.savepoint_started)

    async def test_refuses_forged_hash_before_db(self):
        result, article = fixture()
        from dataclasses import replace
        bad = replace(article, text_sha256="a" * 64)
        session = StubSession()
        with self.assertRaisesRegex(ArticlePipelineError, "text_hash_mismatch"):
            await store_authorized_article(session, discovery_result=result, article=bad,
                                           storage_authorized=True)
        self.assertFalse(session.savepoint_started)

    async def test_refuses_mismatched_article_url(self):
        result, article = fixture()
        from dataclasses import replace
        bad = replace(article, document_url="https://www.bbc.com/news/articles/other")
        session = StubSession()
        with self.assertRaisesRegex(ArticlePipelineError, "extracted_identity_mismatch"):
            await store_authorized_article(session, discovery_result=result, article=bad,
                                           storage_authorized=True)
        self.assertFalse(session.savepoint_started)

    async def test_refuses_claimed_verification(self):
        result, article = fixture()
        from dataclasses import replace
        bad = replace(article, independently_verified=True)
        with self.assertRaisesRegex(ArticlePipelineError, "verified_claim_not_allowed"):
            await store_authorized_article(StubSession(), discovery_result=result, article=bad,
                                           storage_authorized=True)

    async def test_refuses_multiple_hits(self):
        result, article = fixture()
        bad = DiscoveryResult(provider=result.provider, query=result.query, hits=result.hits * 2)
        with self.assertRaisesRegex(ArticlePipelineError, "exactly_one_discovery_hit_required"):
            await store_authorized_article(StubSession(), discovery_result=bad, article=article,
                                           storage_authorized=True)

    async def test_store_calls_existing_services_and_preserves_metadata(self):
        result, article = fixture()
        session = StubSession()
        returned = SimpleNamespace(document_id=uuid4(), document_version_id=uuid4(),
                                   retrieval_observation_id=uuid4(), passages_count=2,
                                   queued_for_indexing=True)
        with patch('apps.api.services.article_content_pipeline.ingest_discovery_result',
                   new_callable=AsyncMock) as discovery, patch(
                'apps.api.services.article_content_pipeline.ingest_supplied_content',
                new_callable=AsyncMock, return_value=returned) as ingest:
            out = await store_authorized_article(session, discovery_result=result, article=article,
                                                 storage_authorized=True)
        discovery.assert_awaited_once()
        ingest.assert_awaited_once()
        self.assertEqual(ingest.await_args.kwargs['provider'], 'secure_article_fetch_v1')
        self.assertEqual(ingest.await_args.kwargs['content_type'], 'text/plain')
        self.assertTrue(ingest.await_args.kwargs['storage_authorized'])
        self.assertTrue(session.savepoint_started)
        self.assertEqual(out.document_version_id, returned.document_version_id)
        self.assertFalse(out.independently_verified)
        self.assertEqual(session.observation.metadata_json['html_sha256'], article.html_sha256)
        self.assertFalse(session.observation.metadata_json['independently_verified'])

    async def test_network_denied_if_no_permission(self):
        result, article = fixture()
        fetch = unittest.mock.Mock(side_effect=AssertionError('should not fetch'))
        with self.assertRaisesRegex(ArticlePipelineError, 'publisher_access_not_approved'):
            await fetch_extract_store_authorized_article(
                StubSession(), discovery_result=result,
                approved_publisher_domains=frozenset({'www.bbc.com'}),
                storage_authorized=True, fetcher=fetch)
        fetch.assert_not_called()

    async def test_network_denied_if_storage_not_authorized(self):
        result, article = fixture()
        fetch = unittest.mock.Mock(side_effect=AssertionError('should not fetch'))
        with self.assertRaisesRegex(ArticlePipelineError, 'storage_not_authorized'):
            await fetch_extract_store_authorized_article(
                StubSession(), discovery_result=result,
                approved_publisher_domains=frozenset({'www.bbc.com'}),
                publisher_access_approved=True, fetcher=fetch)
        fetch.assert_not_called()

    async def test_network_denied_if_not_allowlisted(self):
        result, article = fixture()
        fetch = unittest.mock.Mock(side_effect=AssertionError('should not fetch'))
        with self.assertRaisesRegex(ArticlePipelineError, 'publisher_not_approved'):
            await fetch_extract_store_authorized_article(
                StubSession(), discovery_result=result,
                approved_publisher_domains=frozenset({'www.npr.org'}),
                publisher_access_approved=True, storage_authorized=True, fetcher=fetch)
        fetch.assert_not_called()

    async def test_full_mock_pipeline(self):
        result, article = fixture()
        fetched = FetchedArticleHtml(fetched_url=URL, html_body=HTML, content_type='text/html',
                                     retrieved_at=NOW)
        fetch = unittest.mock.Mock(return_value=fetched)
        extract = unittest.mock.Mock(return_value=article)
        expected = object()
        with patch('apps.api.services.article_content_pipeline.store_authorized_article',
                   new_callable=AsyncMock, return_value=expected) as store:
            out = await fetch_extract_store_authorized_article(
                StubSession(), discovery_result=result,
                approved_publisher_domains=frozenset({'www.bbc.com'}),
                publisher_access_approved=True, storage_authorized=True,
                fetcher=fetch, extractor=extract)
        self.assertIs(out, expected)
        fetch.assert_called_once()
        extract.assert_called_once()
        store.assert_awaited_once()

    async def test_full_pipeline_refuses_html_hash_disagreement(self):
        result, article = fixture()
        from dataclasses import replace
        fetched = FetchedArticleHtml(fetched_url=URL, html_body=HTML, content_type='text/html',
                                     retrieved_at=NOW)
        forged = replace(article, html_sha256='a' * 64)
        with patch('apps.api.services.article_content_pipeline.store_authorized_article',
                   new_callable=AsyncMock) as store:
            with self.assertRaisesRegex(ArticlePipelineError, 'html_hash_mismatch'):
                await fetch_extract_store_authorized_article(
                    StubSession(), discovery_result=result,
                    approved_publisher_domains=frozenset({'www.bbc.com'}),
                    publisher_access_approved=True, storage_authorized=True,
                    fetcher=lambda **kwargs: fetched, extractor=lambda **kwargs: forged)
        store.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()

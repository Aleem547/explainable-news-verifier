"""Phase 13C.4: trusted synthetic HTML -> real extraction -> PostgreSQL rollback.

No HTTP requests, publisher content, evidence claims, AWS access, or DB commits.
The fetcher is a deterministic in-memory stub; the *real* Trafilatura
extractor is exercised when available. Database integration is opt-in.
"""
from __future__ import annotations

import importlib.util
import os
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from apps.api.connectors.contracts import ContentKind, DiscoveryResult, ExternalDiscoveryHit, Provider
from apps.api.services.article_fetch import FetchedArticleHtml
from apps.api.services.article_content_pipeline import fetch_extract_store_authorized_article
from ml.provenance.identity import sha256_text

STAMP = datetime(2026, 10, 19, tzinfo=timezone.utc)
DOMAIN = "news.example.com"   # Reserved example.com namespace, never contacted.
PARAGRAPH = (
    "Investigators published a comprehensive report about a public announcement. "
    "The statement included specific dates, institutional context, and a discussion "
    "of how officials expected the process to proceed following the announcement. "
)
HTML = (
    "<html lang='en'><head><title>A synthetic news report</title>"
    '<meta name="author" content="Test Reporter"></head>'
    '<body><main><article><h1>A synthetic news report</h1>'
    + "".join("<p>" + PARAGRAPH + "</p>" for _ in range(5))
    + "</article></main></body></html>"
).encode("utf-8")


def synthetic_result() -> DiscoveryResult:
    # New URL per test avoids interference with prior local data.
    url = f"https://{DOMAIN}/articles/phase13c4-{uuid4().hex}"
    hit = ExternalDiscoveryHit(
        provider=Provider.RSS_FEED,
        kind=ContentKind.NEWS_ARTICLE,
        url=url,
        publisher_domain=DOMAIN,
        publisher_name="Synthetic News (test only)",
        title="A synthetic news report",
        snippet="Not evidence; synthetic test metadata",
        discovered_at=STAMP,
        published_at=STAMP,
    )
    return DiscoveryResult(provider=Provider.RSS_FEED, query="synthetic report", hits=(hit,))


def stub_fetcher_for(result: DiscoveryResult) -> Mock:
    url = result.hits[0].url
    return Mock(return_value=FetchedArticleHtml(
        fetched_url=url,
        html_body=HTML,
        content_type="text/html; charset=utf-8",
        retrieved_at=STAMP,
    ))


@unittest.skipUnless(importlib.util.find_spec("trafilatura"), "Trafilatura is required")
class OfflineFullFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_extractor_called_with_synthetic_html_without_network(self):
        result = synthetic_result()
        fetcher = stub_fetcher_for(result)
        stored = object()
        with patch(
            "apps.api.services.article_content_pipeline.store_authorized_article",
            new_callable=AsyncMock,
            return_value=stored,
        ) as store:
            output = await fetch_extract_store_authorized_article(
                object(),
                discovery_result=result,
                approved_publisher_domains=frozenset({DOMAIN}),
                publisher_access_approved=True,  # Synthetic fixture only.
                storage_authorized=True,  # Synthetic fixture only.
                fetcher=fetcher,
                # Real Trafilatura is used by default, not a mocked extractor.
            )
        self.assertIs(output, stored)
        fetcher.assert_called_once()
        store.assert_awaited_once()
        extracted = store.await_args.kwargs["article"]
        self.assertIn("Investigators published", extracted.text)
        self.assertGreaterEqual(len(extracted.text), 100)
        self.assertEqual(extracted.document_url, result.hits[0].url)
        self.assertEqual(extracted.html_sha256, sha256(HTML).hexdigest())
        self.assertEqual(extracted.text_sha256, sha256_text(extracted.text))
        self.assertFalse(extracted.independently_verified)
        self.assertTrue(store.await_args.kwargs["storage_authorized"])


@unittest.skipUnless(
    os.environ.get("PHASE13C4_LOCAL_DB_TEST") == "1"
    and importlib.util.find_spec("trafilatura") is not None,
    "Opt-in via local-only runner; Trafilatura must be installed",
)
class LocalPostgresFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        """Close pooled asyncpg connections before the test event loop is closed."""
        from apps.api.db.session import engine
        await engine.dispose()

    async def test_extract_store_verify_provenance_then_rollback(self):
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import AsyncSession
        from apps.api.db.session import engine
        from apps.api.db.models.discovery_record import DiscoveryRecord
        from apps.api.db.models.document import Document
        from apps.api.db.models.document_version import DocumentVersion
        from apps.api.db.models.document_passage import DocumentPassage
        from apps.api.db.models.evidence import Evidence
        from apps.api.db.models.index_outbox import IndexOutbox
        from apps.api.db.models.retrieval_observation import RetrievalObservation

        # Reject misconfigured test databases; never touch production.
        if engine.url.drivername != "postgresql+asyncpg":
            self.fail("Refusing integration test outside PostgreSQL+asyncpg")
        if engine.url.host not in ("127.0.0.1", "localhost", "::1"):
            self.fail("Refusing non-loopback database address")
        if engine.url.database != "verifier":
            self.fail("Refusing unexpected database name")

        result = synthetic_result()
        url = result.hits[0].url
        fetcher = stub_fetcher_for(result)

        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    first = await fetch_extract_store_authorized_article(
                        session,
                        discovery_result=result,
                        approved_publisher_domains=frozenset({DOMAIN}),
                        publisher_access_approved=True,
                        storage_authorized=True,
                        fetcher=fetcher,
                    )
                    second = await fetch_extract_store_authorized_article(
                        session,
                        discovery_result=result,
                        approved_publisher_domains=frozenset({DOMAIN}),
                        publisher_access_approved=True,
                        storage_authorized=True,
                        fetcher=fetcher,
                    )
                    self.assertEqual(first.document_id, second.document_id)
                    self.assertEqual(first.document_version_id, second.document_version_id)
                    self.assertGreater(first.passages_count, 0)
                    self.assertFalse(first.independently_verified)
                    self.assertEqual(fetcher.call_count, 2)

                    doc = await session.scalar(select(Document).where(Document.url == url))
                    self.assertIsNotNone(doc)
                    self.assertEqual(doc.content_hash, sha256_text(doc.raw_text))
                    self.assertIn("Investigators published", doc.raw_text)

                    async def count(model, where):
                        return await session.scalar(
                            select(func.count()).select_from(model).where(where)
                        )

                    self.assertEqual(await count(DocumentVersion,
                        DocumentVersion.document_id == doc.id), 1)
                    self.assertEqual(await count(DiscoveryRecord,
                        DiscoveryRecord.document_id == doc.id), 1)
                    self.assertEqual(await count(IndexOutbox,
                        IndexOutbox.document_version_id == first.document_version_id), 1)
                    self.assertEqual(await count(DocumentPassage,
                        DocumentPassage.document_version_id == first.document_version_id),
                        first.passages_count)
                    self.assertEqual(await count(RetrievalObservation,
                        RetrievalObservation.document_id == doc.id), 2)
                    self.assertEqual(await count(Evidence,
                        Evidence.document_id == doc.id), 0)

                    observation = await session.get(
                        RetrievalObservation, first.retrieval_observation_id
                    )
                    self.assertEqual(observation.metadata_json["html_sha256"],
                                     sha256(HTML).hexdigest())
                    self.assertEqual(observation.metadata_json["text_sha256"],
                                     doc.content_hash)
                    self.assertFalse(observation.metadata_json["independently_verified"])
                    self.assertEqual(observation.provider, "secure_article_fetch_v1")
                    # Commit the session savepoint, not the outer transaction.
                    await session.commit()
            finally:
                if outer.is_active:
                    await outer.rollback()

        async with engine.connect() as connection:
            remaining = await connection.scalar(
                select(func.count()).select_from(Document).where(Document.url == url)
            )
            self.assertEqual(remaining, 0, "Synthetic record was not rolled back")


if __name__ == "__main__":
    unittest.main()

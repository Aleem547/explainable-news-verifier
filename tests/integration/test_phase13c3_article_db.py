"""Rollback-only local PostgreSQL test for Phase 13C.3.

No internet access or actual publisher content. Refuses non-loopback or
non-development databases; always rolls back the enclosing transaction.
"""

import os
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from apps.api.connectors.contracts import (
    ContentKind, DiscoveryResult, ExternalDiscoveryHit, Provider,
)
from apps.api.services.article_extraction import ExtractedArticle
from ml.provenance.identity import sha256_text


def _fixture():
    suffix = uuid4().hex
    url = f"https://www.bbc.com/news/articles/phase13c3-{suffix}"
    text = ("Synthetic article body for local transactional storage. " * 9).strip()
    html = ("<html><article>" + text + "</article></html>").encode('utf-8')
    stamp = datetime.now(timezone.utc)
    hit = ExternalDiscoveryHit(
        provider=Provider.RSS_FEED, kind=ContentKind.NEWS_ARTICLE,
        url=url, publisher_domain="www.bbc.com", publisher_name="BBC News",
        title="Phase 13C.3 local synthetic test", snippet=None,
        discovered_at=stamp, published_at=stamp,
    )
    result = DiscoveryResult(provider=Provider.RSS_FEED, query=f"synthetic {suffix}", hits=(hit,))
    article = ExtractedArticle(
        document_url=url, publisher_domain="www.bbc.com", publisher_name="BBC News",
        text=text, text_sha256=sha256_text(text), html_sha256=sha256(html).hexdigest(),
        title=hit.title, author=None, reported_publication_date=None,
        retrieved_at=stamp,
    )
    return result, article


class OfflineFixtureTest(unittest.TestCase):
    def test_fixture_is_unverified_and_consistent(self):
        result, article = _fixture()
        self.assertEqual(result.hits[0].url, article.document_url)
        self.assertEqual(article.text_sha256, sha256_text(article.text))
        self.assertFalse(article.independently_verified)


@unittest.skipUnless(
    os.environ.get('PHASE13C3_LOCAL_DB_TEST') == '1',
    'Set PHASE13C3_LOCAL_DB_TEST=1 via the provided local-only PowerShell runner',
)
class ArticleDatabaseIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_store_idempotently_then_roll_back_everything(self):
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import AsyncSession
        from apps.api.db.session import engine
        from apps.api.db.models.document import Document
        from apps.api.db.models.document_version import DocumentVersion
        from apps.api.db.models.document_passage import DocumentPassage
        from apps.api.db.models.discovery_record import DiscoveryRecord
        from apps.api.db.models.retrieval_observation import RetrievalObservation
        from apps.api.db.models.index_outbox import IndexOutbox
        from apps.api.services.article_content_pipeline import store_authorized_article

        if engine.url.drivername != 'postgresql+asyncpg':
            self.fail('Refusing test: expected PostgreSQL+asyncpg')
        if engine.url.host not in ('127.0.0.1', 'localhost', '::1'):
            self.fail('Refusing test: database must be on loopback')
        if engine.url.database != 'verifier':
            self.fail('Refusing test: expected local database verifier')

        result, article = _fixture()
        url = article.document_url
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode='create_savepoint',
                ) as session:
                    first = await store_authorized_article(
                        session, discovery_result=result, article=article,
                        storage_authorized=True,
                    )
                    second = await store_authorized_article(
                        session, discovery_result=result, article=article,
                        storage_authorized=True,
                    )
                    self.assertEqual(first.document_id, second.document_id)
                    self.assertEqual(first.document_version_id, second.document_version_id)
                    self.assertFalse(first.independently_verified)
                    self.assertGreater(first.passages_count, 0)

                    document = await session.scalar(select(Document).where(Document.url == url))
                    self.assertIsNotNone(document)
                    self.assertEqual(document.raw_text, article.text)
                    self.assertEqual(document.content_hash, article.text_sha256)

                    async def count(model, clause):
                        statement = select(func.count()).select_from(model).where(clause)
                        return await session.scalar(statement)

                    versions = await count(
                        DocumentVersion, DocumentVersion.document_id == document.id
                    )
                    self.assertEqual(versions, 1)
                    records = await count(
                        DiscoveryRecord, DiscoveryRecord.document_id == document.id
                    )
                    self.assertEqual(records, 1)
                    passages = await count(
                        DocumentPassage,
                        DocumentPassage.document_version_id == first.document_version_id,
                    )
                    self.assertEqual(passages, first.passages_count)
                    self.assertEqual(await count(IndexOutbox,
                        IndexOutbox.document_version_id == first.document_version_id), 1)
                    self.assertEqual(await count(RetrievalObservation,
                        RetrievalObservation.document_id == document.id), 2)

                    observation = await session.get(
                        RetrievalObservation, first.retrieval_observation_id
                    )
                    self.assertEqual(observation.metadata_json['html_sha256'], article.html_sha256)
                    self.assertFalse(observation.metadata_json['independently_verified'])
                    self.assertEqual(observation.provider, 'secure_article_fetch_v1')
                    await session.commit()  # savepoint only, NOT enclosing transaction
            finally:
                if outer.is_active:
                    await outer.rollback()

        async with engine.connect() as connection:
            remaining = await connection.scalar(
                select(func.count()).select_from(Document).where(Document.url == url)
            )
            self.assertEqual(remaining, 0, 'Synthetic article escaped transaction rollback')


if __name__ == '__main__':
    unittest.main()

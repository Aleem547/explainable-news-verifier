"""Phase 13B.7: RSS discovery -> existing ingestion service -> PostgreSQL.

Safety guarantees:
* No external HTTP requests; the RSS feed is an in-memory test fixture.
* No direct SQL INSERT or COMMIT against the database.
* A surrounding PostgreSQL transaction is ALWAYS rolled back, including if
  the application session commits its own savepoint.
* Refuses any non-loopback / non-development database connection.
* Only runs the database check when explicitly enabled by the operator.

Run from the repository root via scripts/phase13b7/run_local_rss_db_test.ps1.
"""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from uuid import uuid4

from apps.api.connectors.contracts import DiscoveryRequest, DiscoveryResult, Provider
from apps.api.connectors.rss import RSS_FEEDS, parse_rss_items


def _synthetic_rss_result() -> DiscoveryResult:
    """A unique BBC-format URL, never fetched; no publisher content retained."""
    token = uuid4().hex
    query = f"Phase13B7 synthetic article {token}"
    url = f"https://www.bbc.com/news/articles/phase13b7-{token}"
    feed_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<rss version="2.0"><channel><title>Test feed</title><item>'
        f'<title>{query}</title>'
        f'<link>{url}</link>'
        '<description>Local metadata-only integration test</description>'
        '<pubDate>Sun, 18 Oct 2026 12:30:00 GMT</pubDate>'
        '</item></channel></rss>'
    ).encode("utf-8")
    hits = parse_rss_items(
        feed_xml,
        RSS_FEEDS[0],
        DiscoveryRequest(query=query, limit=1),
        datetime.now(UTC),
    )
    if len(hits) != 1:
        raise AssertionError("Synthetic trusted RSS fixture did not produce one hit")
    return DiscoveryResult(provider=Provider.RSS_FEED, query=query, hits=hits)


class RssDatabaseFixtureTest(unittest.TestCase):
    def test_synthetic_rss_produces_only_metadata(self) -> None:
        result = _synthetic_rss_result()
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(result.provider, Provider.RSS_FEED)
        self.assertEqual(result.hits[0].provider, Provider.RSS_FEED)
        self.assertIsNone(result.hits[0].snippet)
        self.assertEqual(result.hits[0].publisher_name, "BBC News")
        self.assertTrue(result.hits[0].url.startswith("https://www.bbc.com/"))


@unittest.skipUnless(
    os.environ.get("PHASE13B7_LOCAL_DB_TEST") == "1",
    "Set PHASE13B7_LOCAL_DB_TEST=1 to enable the rollback-only local DB test",
)
class RssDatabaseIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_ingestion_duplicates_and_full_rollback(self) -> None:
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import AsyncSession

        from apps.api.db.models.discovery_record import DiscoveryRecord
        from apps.api.db.models.document import Document
        from apps.api.db.models.source import Source
        from apps.api.db.session import engine  # existing configured application engine
        from apps.api.services.external_ingestion import ingest_discovery_result

        if engine.url.drivername != "postgresql+asyncpg":
            self.fail("Refusing test: expected PostgreSQL+asyncpg")
        if engine.url.host not in ("127.0.0.1", "localhost", "::1"):
            self.fail("Refusing test: database host is not loopback")
        if engine.url.database != "verifier":
            self.fail("Refusing test: expected local development database named 'verifier'")

        result = _synthetic_rss_result()
        url = result.hits[0].url
        doc_id = None

        # The outer transaction stays open while the nested session uses its
        # own savepoint. Even a session.commit() below cannot persist this test.
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    first = await ingest_discovery_result(session, result)
                    second = await ingest_discovery_result(session, result)
                    self.assertEqual(first.documents_seen, 1)
                    self.assertEqual(first.discovery_records_seen, 1)
                    self.assertEqual(second.documents_seen, 1)
                    self.assertEqual(second.discovery_records_seen, 1)

                    document = await session.scalar(select(Document).where(Document.url == url))
                    self.assertIsNotNone(document)
                    doc_id = document.id
                    self.assertIsNone(document.raw_text)  # metadata, not article content
                    self.assertIsNone(document.content_hash)

                    source = await session.scalar(select(Source).where(Source.id == document.source_id))
                    self.assertIsNotNone(source)
                    self.assertEqual(source.domain, result.hits[0].publisher_domain)

                    doc_count = await session.scalar(
                        select(func.count()).select_from(Document).where(Document.url == url)
                    )
                    record_count = await session.scalar(
                        select(func.count()).select_from(DiscoveryRecord).where(
                            DiscoveryRecord.document_id == doc_id,
                            DiscoveryRecord.provider == Provider.RSS_FEED.value,
                        )
                    )
                    self.assertEqual(doc_count, 1)
                    self.assertEqual(record_count, 1)  # idempotent after second ingest

                    # Commit the *session savepoint*, not the protected outer transaction.
                    await session.commit()
                outer_visible = await connection.scalar(
                    select(func.count()).select_from(Document).where(Document.url == url)
                )
                self.assertEqual(outer_visible, 1)
            finally:
                # Rolls back source, document and discovery record, on success/failure.
                if outer.is_active:
                    await outer.rollback()

        # Verify with a NEW connection that no sample document persisted.
        async with engine.connect() as new_connection:
            remaining = await new_connection.scalar(
                select(func.count()).select_from(Document).where(Document.url == url)
            )
            self.assertEqual(remaining, 0, "A synthetic test document escaped rollback")


if __name__ == "__main__":
    unittest.main()

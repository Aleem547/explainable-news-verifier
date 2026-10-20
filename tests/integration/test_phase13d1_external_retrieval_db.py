"""Read-only retrieval integration over rollback-only synthetic article snapshots.

No network requests, no test commits, no real publisher content.
Requires environment variables PHASE13D1_PG_USER, PHASE13D1_PG_PASSWORD,
PHASE13D1_PG_DB, PHASE13D1_PG_PORT. Windows runner populates them from the
local development PostgreSQL Docker container.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from apps.api.connectors.contracts import ContentKind, DiscoveryResult, ExternalDiscoveryHit, Provider
from apps.api.db.models.retrieval_observation import RetrievalObservation
from apps.api.services.external_ingestion import ingest_discovery_result, ingest_supplied_content
from apps.api.services.external_passage_retrieval import retrieve_external_passages


class LocalDatabaseTest(unittest.TestCase):
    def test_synthetic_evidence_retrieval_rollback(self):
        user = os.environ.get("PHASE13D1_PG_USER")
        password = os.environ.get("PHASE13D1_PG_PASSWORD")
        database = os.environ.get("PHASE13D1_PG_DB")
        port = os.environ.get("PHASE13D1_PG_PORT", "5432")
        if not all((user, password, database)):
            self.fail("Use scripts/phase13d1/run_local_external_retrieval.ps1; local credentials missing")
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            self.fail("Invalid local PostgreSQL port")

        async def run() -> None:
            # No URL from configuration: the address is hard-coded to loopback.
            engine = create_async_engine(
                URL.create(
                    "postgresql+asyncpg", username=user, password=password,
                    host="127.0.0.1", port=int(port), database=database,
                ),
                poolclass=NullPool,
                connect_args={"timeout": 8},
            )
            transaction = None
            try:
                async with engine.connect() as conn:
                    transaction = await conn.begin()
                    try:
                        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                            now = datetime.now(UTC)
                            hostname = f"phase13d1-{uuid4().hex}.example.org"
                            url = f"https://{hostname}/synthetic-public-article"
                            hit = ExternalDiscoveryHit(
                                provider=Provider.RSS_FEED,
                                kind=ContentKind.NEWS_ARTICLE,
                                url=url,
                                publisher_domain=hostname,
                                publisher_name="Synthetic Source",
                                title="Local synthetic climate report",
                                snippet="The headline claims a solar project exists.",
                                discovered_at=now,
                                published_at=now,
                                language="en",
                            )
                            discovery = DiscoveryResult(
                                provider=Provider.RSS_FEED,
                                query="synthetic solar energy",
                                hits=(hit,),
                            )
                            await ingest_discovery_result(session, discovery)
                            # Discovery-only content must NEVER become a candidate.
                            before = await retrieve_external_passages(
                                session, claim="zyphra renewable solar energy", top_k=10,
                            )
                            self.assertFalse(any(x.original_url == url for x in before))

                            article_text = (
                                "The zyphra renewable solar energy project began in the valley. "
                                "Engineers documented several measurements and published "
                                "the results to show that solar panels supplied electricity "
                                "to the treatment station during a controlled demonstration. "
                                "These sentences are entirely synthetic test data."
                            )
                            content = await ingest_supplied_content(
                                session, url=url, text=article_text, retrieved_at=now,
                                storage_authorized=True, provider="secure_article_fetch_v1",
                            )
                            observation = await session.get(
                                RetrievalObservation, content.retrieval_observation_id
                            )
                            self.assertIsNotNone(observation)
                            observation.metadata_json = {
                                "independently_verified": False,
                                "extraction_method": "synthetic_local_fixture",
                            }
                            await session.flush()
                            results = await retrieve_external_passages(
                                session, claim="zyphra renewable solar energy", top_k=10,
                            )
                            matched = [x for x in results if x.original_url == url]
                            self.assertTrue(matched, "Fully stored article not retrieved")
                            self.assertEqual(matched[0].publisher_domain, hostname)
                            self.assertEqual(matched[0].document_version_id, content.document_version_id)
                            self.assertEqual(matched[0].source_id, observation.source_id)
                            self.assertIn("zyphra renewable solar energy", matched[0].passage_text)
                            self.assertFalse(matched[0].independently_verified)
                            self.assertFalse(matched[0].nli_evaluated)
                            # Retrieval is read only; it creates no new observations.
                            count_after = await session.scalar(
                                select(RetrievalObservation.id).where(
                                    RetrievalObservation.document_version_id == content.document_version_id
                                )
                            )
                            self.assertEqual(count_after, content.retrieval_observation_id)
                    finally:
                        if transaction is not None and transaction.is_active:
                            await transaction.rollback()
            finally:
                await engine.dispose()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

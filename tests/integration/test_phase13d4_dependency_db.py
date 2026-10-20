"""Phase 13D.4 rollback-only local PostgreSQL audit: no HTTP requests."""
from __future__ import annotations

import asyncio
import os
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from apps.api.connectors.contracts import ContentKind, DiscoveryResult, ExternalDiscoveryHit, Provider
from apps.api.db.models.document import Document
from apps.api.db.models.retrieval_observation import RetrievalObservation
from apps.api.services.external_ingestion import ingest_discovery_result, ingest_supplied_content
from apps.api.services.external_passage_retrieval import retrieve_external_passages
from apps.api.services.external_source_independence import audit_external_source_dependencies


class LocalSourceDependencyDatabaseTest(unittest.TestCase):
    def test_syndicated_content_risk_then_full_rollback(self):
        user = os.environ.get("PHASE13D4_PG_USER")
        password = os.environ.get("PHASE13D4_PG_PASSWORD")
        database = os.environ.get("PHASE13D4_PG_DB")
        port = os.environ.get("PHASE13D4_PG_PORT", "5432")
        if not all((user, password, database)) or not port.isdigit() or not 1 <= int(port) <= 65535:
            self.fail("Use scripts/phase13d4/run_local_independence.ps1 with local Docker PostgreSQL")

        async def run():
            engine = create_async_engine(
                URL.create("postgresql+asyncpg", username=user, password=password,
                           host="127.0.0.1", port=int(port), database=database),
                poolclass=NullPool, connect_args={"timeout": 8},
            )
            hostnames = [f"phase13d4-{uuid4().hex}.example.org" for _ in range(2)]
            urls = [f"https://{name}/fixture-report" for name in hostnames]
            now = datetime.now(UTC)
            text = (
                "The zyphra solar dependency trial conducted a controlled inspection "
                "and produced an entirely synthetic public-report fixture for the "
                "source independence verification tests. Researchers measured changes "
                "and recorded the same summary on multiple publisher domains. "
                "These sentences are mock laboratory content and not actual reporting. "
            ) * 3
            try:
                async with engine.connect() as conn:
                    tx = await conn.begin()
                    try:
                        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                            for url, host in zip(urls, hostnames, strict=True):
                                hit = ExternalDiscoveryHit(
                                    provider=Provider.RSS_FEED, kind=ContentKind.NEWS_ARTICLE,
                                    url=url, publisher_domain=host, publisher_name=host,
                                    title="Synthetic dependency fixture", snippet="Not evidence",
                                    discovered_at=now, published_at=now, language="en",
                                )
                                await ingest_discovery_result(
                                    session, DiscoveryResult(
                                        provider=Provider.RSS_FEED,
                                        query="zyphra solar dependency",
                                        hits=(hit,),
                                    ),
                                )
                                content = await ingest_supplied_content(
                                    session, url=url, text=text, retrieved_at=now,
                                    storage_authorized=True, provider="secure_article_fetch_v1",
                                )
                                observation = await session.get(
                                    RetrievalObservation, content.retrieval_observation_id,
                                )
                                self.assertIsNotNone(observation)
                                observation.metadata_json = {"independently_verified": False}
                            await session.flush()
                            candidates = await retrieve_external_passages(
                                session, claim="zyphra solar dependency", top_k=20,
                                candidate_limit=40,
                            )
                            picks = [next((row for row in candidates if row.original_url == url), None)
                                     for url in urls]
                            self.assertTrue(all(picks), "Missing synthetic source candidates")
                            report = await audit_external_source_dependencies(
                                session, picks, assessed_at=now + timedelta(seconds=5),
                            )
                            self.assertEqual(len(report.version_ids), 2)
                            self.assertEqual(report.risk_family_count, 1)
                            self.assertEqual(report.pairs[0].relationship, "IDENTICAL_TEXT")
                            self.assertFalse(report.independent_corroboration_established)
                            self.assertFalse(report.nli_evaluated)
                    finally:
                        if tx.is_active:
                            await tx.rollback()
                async with engine.connect() as conn:
                    rows = (await conn.scalars(select(Document.url).where(Document.url.in_(urls)))).all()
                    self.assertEqual(rows, [])
            finally:
                await engine.dispose()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

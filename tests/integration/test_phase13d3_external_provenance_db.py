"""Phase 13D.3 rollback-only PostgreSQL source provenance integration.

Requires the local development Docker Postgres. It never fetches any URL.
Synthetic article and observation rows are created inside a rolled-back transaction.
"""
from __future__ import annotations

import asyncio
import os
import unittest
from dataclasses import replace
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
from apps.api.services.external_evidence_provenance import (
    ExternalProvenanceError, audit_external_passage_provenance,
)


class LocalProvenanceDatabaseTest(unittest.TestCase):
    def test_complete_snapshot_source_fetch_chain_then_rollback(self):
        user = os.environ.get("PHASE13D3_PG_USER")
        password = os.environ.get("PHASE13D3_PG_PASSWORD")
        database = os.environ.get("PHASE13D3_PG_DB")
        port = os.environ.get("PHASE13D3_PG_PORT", "5432")
        if not all((user, password, database)) or not port.isdigit() or not 1 <= int(port) <= 65535:
            self.fail("Run with scripts/phase13d3/run_local_provenance.ps1 and local Docker Postgres")

        async def run():
            engine = create_async_engine(
                URL.create("postgresql+asyncpg", username=user, password=password,
                           host="127.0.0.1", port=int(port), database=database),
                poolclass=NullPool, connect_args={"timeout": 8},
            )
            try:
                async with engine.connect() as conn:
                    tx = await conn.begin()
                    try:
                        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                            now = datetime.now(UTC)
                            hostname = f"phase13d3-{uuid4().hex}.example.org"
                            url = f"https://{hostname}/synthetic-source-report"
                            hit = ExternalDiscoveryHit(
                                provider=Provider.RSS_FEED, kind=ContentKind.NEWS_ARTICLE,
                                url=url, publisher_domain=hostname,
                                publisher_name="Synthetic Provenance Publisher",
                                title="Synthetic provenance test", snippet="Not evidence",
                                discovered_at=now, published_at=now, language="en",
                            )
                            discovery = DiscoveryResult(
                                provider=Provider.RSS_FEED, query="synthetic provenance project",
                                hits=(hit,),
                            )
                            await ingest_discovery_result(session, discovery)
                            before = await retrieve_external_passages(
                                session, claim="zyphra solar provenance", top_k=10,
                            )
                            self.assertFalse(any(x.original_url == url for x in before))
                            text = (
                                "The zyphra solar provenance trial completed several verified measurements "
                                "and published a synthetic report in a demonstration laboratory. "
                                "This is fixture content and not a factual news publication. "
                                "Researchers recorded results solely to test immutable document passages."
                            )
                            content = await ingest_supplied_content(
                                session, url=url, text=text, retrieved_at=now,
                                storage_authorized=True, provider="secure_article_fetch_v1",
                            )
                            observation = await session.get(
                                RetrievalObservation, content.retrieval_observation_id,
                            )
                            self.assertIsNotNone(observation)
                            observation.metadata_json = {
                                "independently_verified": False,
                                "extraction_method": "synthetic_provenance_fixture",
                            }
                            await session.flush()
                            candidates = await retrieve_external_passages(
                                session, claim="zyphra solar provenance", top_k=10,
                            )
                            matches = [candidate for candidate in candidates if candidate.original_url == url]
                            self.assertTrue(matches, "Synthetic passage not retrieved")
                            result = await audit_external_passage_provenance(session, matches)
                            self.assertEqual(len(result), len(matches))
                            self.assertTrue(result[0].traceable)
                            self.assertEqual(result[0].fetch_observation_id, observation.id)
                            self.assertFalse(result[0].independently_verified)
                            self.assertFalse(result[0].independent_corroboration_established)
                            with self.assertRaises(ExternalProvenanceError):
                                await audit_external_passage_provenance(
                                    session, [replace(matches[0], publisher_name="Spoofed Publisher")],
                                )
                            saved = await session.scalar(select(RetrievalObservation.id).where(
                                RetrievalObservation.document_version_id == content.document_version_id,
                            ))
                            self.assertEqual(saved, observation.id)
                    finally:
                        if tx.is_active:
                            await tx.rollback()
            finally:
                await engine.dispose()
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

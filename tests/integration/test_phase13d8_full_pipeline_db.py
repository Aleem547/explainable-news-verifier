"""Phase 13D.8 synthetic rollback-only full pipeline integration test.

Runs against existing local 127.0.0.1 PostgreSQL. No news API, HTTP requests,
paid services, model downloads or actual DeBERTa model execution. A controlled
NLI predictor is injected. The *actual* model smoke passed earlier in D.5 and
is optionally rerunnable separately.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import os
import unittest
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
from apps.api.services.external_evidence_nli import ExternalNliError, assess_external_evidence_nli
from apps.api.services.external_evidence_agreement import analyze_external_evidence_agreement
from apps.api.services.external_corroboration_decision import decide_external_corroboration, ExternalEvidenceVerdict

CLAIM = "The zyphra solar checkpoint measured a synthetic laboratory result"


class ControlledPredictor:
    """Deterministic fake model: NOT a factual NLI evaluation."""
    def __init__(self, labels):
        self.labels = tuple(labels)
        self.calls = 0

    def predict(self, claim, evidence_texts):
        from types import SimpleNamespace
        self.calls += 1
        if claim != CLAIM or len(evidence_texts) != len(self.labels):
            raise AssertionError("Unexpected predictor request")
        values = {
            "support": (0.97, 0.01, 0.02),
            "refute": (0.01, 0.97, 0.02),
            "neutral": (0.03, 0.03, 0.94),
        }
        return [SimpleNamespace(entailment=e, contradiction=c, neutral=n)
                for e, c, n in (values[label] for label in self.labels)]


class LocalFullPipelineTest(unittest.TestCase):
    def test_retrieval_to_decision_with_rollback(self):
        user = os.environ.get("PHASE13D8_PG_USER")
        password = os.environ.get("PHASE13D8_PG_PASSWORD")
        database = os.environ.get("PHASE13D8_PG_DB")
        port = os.environ.get("PHASE13D8_PG_PORT", "5432")
        if not all((user, password, database)) or not port.isdigit() or not 1 <= int(port) <= 65535:
            self.fail("Run scripts/phase13d8/run_local_phase13d8.ps1 with local Docker PostgreSQL")

        async def run():
            engine = create_async_engine(
                URL.create("postgresql+asyncpg", username=user, password=password,
                           host="127.0.0.1", port=int(port), database=database),
                poolclass=NullPool, connect_args={"timeout": 8},
            )
            hosts = [f"phase13d8-{uuid4().hex}.example.org" for _ in range(3)]
            urls = [f"https://{host}/synthetic-checkpoint" for host in hosts]
            now = datetime.now(UTC)
            assessed_at = now + timedelta(seconds=10)
            repeated = (
                "The zyphra solar checkpoint measured a synthetic laboratory result "
                "during a controlled test. This repeated laboratory report is a "
                "fictional example used only to evaluate provenance and duplicate "
                "evidence grouping across external publication snapshots. "
            ) * 3
            other = (
                "The zyphra solar checkpoint measured a synthetic laboratory result "
                "in a different fictional demonstration, with separate descriptions "
                "of instruments and researchers. The measurements are placeholders "
                "and are not assertions about any real scientific experiment. "
            ) * 3
            texts = (repeated, repeated, other)
            try:
                async with engine.connect() as conn:
                    tx = await conn.begin()
                    try:
                        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                            for url, host, text in zip(urls, hosts, texts, strict=True):
                                hit = ExternalDiscoveryHit(
                                    provider=Provider.RSS_FEED, kind=ContentKind.NEWS_ARTICLE,
                                    url=url, publisher_domain=host, publisher_name=host,
                                    title="Synthetic full-flow source", snippet="Not verified evidence",
                                    discovered_at=now, published_at=now, language="en",
                                )
                                await ingest_discovery_result(session, DiscoveryResult(
                                    provider=Provider.RSS_FEED, query="zyphra solar checkpoint",
                                    hits=(hit,),
                                ))
                                stored = await ingest_supplied_content(
                                    session, url=url, text=text, retrieved_at=now,
                                    storage_authorized=True, provider="secure_article_fetch_v1",
                                )
                                observation = await session.get(
                                    RetrievalObservation, stored.retrieval_observation_id
                                )
                                self.assertIsNotNone(observation)
                                observation.metadata_json = {"independently_verified": False}
                            await session.flush()

                            retrieved = await retrieve_external_passages(
                                session, claim=CLAIM, top_k=20, candidate_limit=60,
                            )
                            selected = [next((r for r in retrieved if r.original_url == u), None) for u in urls]
                            self.assertTrue(all(selected), "Expected all three synthetic sources")
                            candidates = tuple(selected)

                            # Tests Phase 13D.1 -> 13D.3 -> 13D.2 -> 13D.4 -> 13D.5 -> 13D.6 -> 13D.7.
                            predictor = ControlledPredictor(["support", "support", "refute"])
                            report = await assess_external_evidence_nli(
                                session, claim=CLAIM, candidates=candidates,
                                predictor=predictor, assessed_at=assessed_at,
                            )
                            agreement = analyze_external_evidence_agreement(nli_report=report)
                            decision = decide_external_corroboration(
                                nli_report=report, agreement_report=agreement,
                            )
                            self.assertEqual(predictor.calls, 1)
                            self.assertEqual(decision.evidence_verdict, ExternalEvidenceVerdict.CONFLICTING_EVIDENCE)
                            self.assertEqual(decision.provisional_unit_count, 2)
                            self.assertEqual(decision.supporting_unit_count, 1)
                            self.assertEqual(decision.refuting_unit_count, 1)
                            self.assertEqual(set(decision.evidence_passage_ids), {c.passage_id for c in candidates})
                            self.assertFalse(decision.independent_corroboration_established)
                            self.assertFalse(decision.independently_verified)
                            self.assertEqual(decision.independence_status, "NOT_ESTABLISHED")
                            self.assertTrue(all(item.publisher_domain in hosts for item in report.evidence))
                            self.assertEqual(report.dependency_risk_family_count, 2)

                            predictor2 = ControlledPredictor(["support"] * 3)
                            support_report = await assess_external_evidence_nli(
                                session, claim=CLAIM, candidates=candidates,
                                predictor=predictor2, assessed_at=assessed_at,
                            )
                            support = decide_external_corroboration(
                                nli_report=support_report,
                                agreement_report=analyze_external_evidence_agreement(nli_report=support_report),
                            )
                            self.assertEqual(support.evidence_verdict, ExternalEvidenceVerdict.PROVISIONAL_SUPPORT)
                            self.assertEqual(support.provisional_unit_count, 2)
                            self.assertFalse(support.independent_corroboration_established)

                            neutral_predictor = ControlledPredictor(["neutral"] * 3)
                            neutral_report = await assess_external_evidence_nli(
                                session, claim=CLAIM, candidates=candidates,
                                predictor=neutral_predictor, assessed_at=assessed_at,
                            )
                            insufficient = decide_external_corroboration(
                                nli_report=neutral_report,
                                agreement_report=analyze_external_evidence_agreement(nli_report=neutral_report),
                            )
                            self.assertEqual(insufficient.evidence_verdict, ExternalEvidenceVerdict.INSUFFICIENT_EVIDENCE)

                            rejected_predictor = ControlledPredictor(["support"] * 3)
                            with self.assertRaises(ExternalNliError):
                                await assess_external_evidence_nli(
                                    session, claim=CLAIM,
                                    candidates=(replace(candidates[0], passage_text="TAMPERED") , *candidates[1:]),
                                    predictor=rejected_predictor, assessed_at=assessed_at,
                                )
                            self.assertEqual(rejected_predictor.calls, 0)
                    finally:
                        if tx.is_active:
                            await tx.rollback()
                async with engine.connect() as connection:
                    remaining = (await connection.scalars(select(Document.url).where(Document.url.in_(urls)))).all()
                    self.assertEqual(remaining, [], "Synthetic documents survived transaction rollback")
            finally:
                await engine.dispose()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

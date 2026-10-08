"""Opt-in Phase 9G PostgreSQL orchestration smoke test; always rolls back.

Uses a deterministic fake predictor; this is NOT a live NLI quality benchmark.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from apps.api.connectors.contracts import (
    ContentKind,
    DiscoveryResult,
    ExternalDiscoveryHit,
    Provider,
)
from apps.api.core.config import get_settings
from apps.api.db.models.document_passage import DocumentPassage
from apps.api.schemas.multisource import MultiSourceAssessmentRequest
from apps.api.services.external_ingestion import ingest_discovery_result, ingest_supplied_content
from apps.api.services.multisource import PredictionDistribution, evaluate_captured_evidence


@dataclass(frozen=True)
class FakeDistribution:
    def checked(self) -> "FakeDistribution":
        return self

    def top_label(self) -> tuple[str, float]:
        return ("ENTAILMENT", 0.96)


class TestPredictor:
    def predict(
        self, claim: str, evidence_texts: Sequence[str]
    ) -> Sequence[PredictionDistribution]:
        return [FakeDistribution() for _ in evidence_texts]


async def check() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    now = datetime.now(UTC)
                    passage_ids = []
                    for index in range(2):
                        domain = f"phase9g-{uuid4().hex}.example.com"
                        url = f"https://{domain}/story"
                        discovery_payload = DiscoveryResult(
                            provider=Provider.NEWSAPI,
                            query="The Eiffel Tower",
                            hits=(
                                ExternalDiscoveryHit(
                                    provider=Provider.NEWSAPI,
                                    kind=ContentKind.NEWS_ARTICLE,
                                    url=url,
                                    publisher_domain=domain,
                                    publisher_name=f"Phase 9G source {index}",
                                    title="Rollback test story",
                                    snippet="Discovery metadata only, not evidence.",
                                    discovered_at=now,
                                    published_at=now - timedelta(days=2),
                                ),
                            ),
                        )
                        discovered = await ingest_discovery_result(session, discovery_payload)
                        assert discovered.documents_seen == 1
                        text = (
                            f"The Eiffel Tower stands in Paris according to the synthetic "
                            f"sample statement from source {index}. "
                        ) * 4
                        ingested = await ingest_supplied_content(
                            session,
                            url=url,
                            text=text,
                            retrieved_at=now,
                            storage_authorized=True,
                            provider="phase9g_smoke_authorized_synthetic",
                        )
                        stored = (
                            await session.scalars(
                                select(DocumentPassage).where(
                                    DocumentPassage.document_version_id
                                    == ingested.document_version_id
                                )
                            )
                        ).all()
                        assert stored
                        passage = stored[0]
                        passage_ids.append(passage.id)
                    request = MultiSourceAssessmentRequest(
                        claim="The Eiffel Tower is in Paris",
                        passage_ids=passage_ids,
                        reference_at=now,
                        max_age_days=30,
                    )
                    assessment = await evaluate_captured_evidence(
                        session, request, predictor=TestPredictor(), assessed_at=now
                    )
                    assert assessment.outcome == "MULTI_FAMILY_SUPPORT_UNVERIFIED"
                    assert len(assessment.evidence) == 2
                    assert all(row.decision == "ELIGIBLE" for row in assessment.evidence)
                    assert assessment.independent_corroboration_established is False
                    assert assessment.provisional_supporting_families == 2
                    print("Phase 9G PostgreSQL integrated workflow smoke test passed")
            finally:
                await transaction.rollback()
                print("Rolled back the smoke-test transaction")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check())

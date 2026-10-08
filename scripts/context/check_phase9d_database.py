"""Opt-in PostgreSQL smoke test; temporary rows rolled back, no API calls."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from apps.api.core.config import get_settings
from apps.api.db.models.document import Document
from apps.api.db.models.source import Source
from apps.api.services.provenance import capture_document_version, record_retrieval_observation
from apps.api.services.source_context import assess_document_context, record_source_profile
from ml.verification.source_context import SourceObservationMethod


async def check() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    now = datetime.now(UTC)
                    domain = f"phase9d-{uuid4().hex}.example.com"
                    source = Source(name="Phase 9D Rollback Test", domain=domain)
                    session.add(source)
                    await session.flush()
                    document = Document(
                        source_id=source.id,
                        url=f"https://{domain}/test-article",
                        published_at=now - timedelta(days=30),
                        title="Reversible diagnostic example",
                    )
                    session.add(document)
                    await session.flush()
                    version = await capture_document_version(
                        session,
                        document_id=document.id,
                        text="An authorized sample text for a rollback-only integration test.",
                        retrieved_at=now,
                    )
                    observation = await record_retrieval_observation(
                        session,
                        source_id=source.id,
                        provider="phase9d_smoke",
                        requested_url=document.url,
                        final_url=document.url,
                        outcome="FETCHED",
                        observed_at=now,
                        document_id=document.id,
                        document_version_id=version.id,
                    )
                    profile = await record_source_profile(
                        session,
                        source_id=source.id,
                        observed_at=now,
                        method=SourceObservationMethod.MANUAL_RECORD,
                        publisher_name_reported="Phase 9D Rollback Test",
                    )
                    assessment = await assess_document_context(
                        session,
                        document_version_id=version.id,
                        assessed_at=now,
                        claim_text="An example diagnostic claim",
                        reference_at=now - timedelta(days=7),
                        max_age_days=365,
                        source_profile_observation_id=profile.id,
                        retrieval_observation_id=observation.id,
                    )
                    assert assessment.temporal_relation == "BEFORE_REFERENCE"
                    assert assessment.freshness_status == "WITHIN_WINDOW"
                    assert assessment.retrieval_observation_id == observation.id
                    # Read back through the transaction, then roll the entire test back.
                    found = await session.scalar(select(Source).where(Source.id == source.id))
                    assert found is not None
                    print("Phase 9D PostgreSQL transactional smoke test passed")
            finally:
                await transaction.rollback()
                print("Rolled back the smoke-test transaction")
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(check())


if __name__ == "__main__":
    main()

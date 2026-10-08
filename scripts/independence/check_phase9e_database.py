"""Opt-in PostgreSQL test; never commits test data or calls external APIs."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from apps.api.core.config import get_settings
from apps.api.db.models.document import Document
from apps.api.db.models.independence_pair import IndependencePair
from apps.api.db.models.source import Source
from apps.api.services.provenance import capture_document_version
from apps.api.services.source_independence import record_independence_assessment


async def check() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    now = datetime.now(UTC)
                    ids = []
                    text = (
                        "Original sample text for Phase 9E. Shared licensed reporting is "
                        "represented by identical snapshot content rather than domain count. " * 3
                    )
                    for index in range(2):
                        domain = f"phase9e-{uuid4().hex}.example.com"
                        source = Source(name=f"Phase 9E {index}", domain=domain)
                        session.add(source)
                        await session.flush()
                        document = Document(source_id=source.id, url=f"https://{domain}/report")
                        session.add(document)
                        await session.flush()
                        snapshot = await capture_document_version(
                            session, document_id=document.id, text=text, retrieved_at=now
                        )
                        ids.append(snapshot.id)
                    assessment = await record_independence_assessment(
                        session, version_ids=ids, assessed_at=now
                    )
                    assert assessment.family_count == 1
                    pair = await session.scalar(
                        select(IndependencePair).where(
                            IndependencePair.assessment_id == assessment.id
                        )
                    )
                    assert pair is not None and pair.relationship == "IDENTICAL_TEXT"
                    print("Phase 9E PostgreSQL transactional smoke test passed")
            finally:
                await transaction.rollback()
                print("Rolled back the smoke-test transaction")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check())

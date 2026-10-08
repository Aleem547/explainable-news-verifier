"""Optional Phase 9F PostgreSQL smoke test, always rolling back test records."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from apps.api.core.config import get_settings
from apps.api.db.models.cross_source_evidence import CrossSourceEvidence
from apps.api.db.models.document import Document
from apps.api.db.models.document_passage import DocumentPassage
from apps.api.db.models.source import Source
from apps.api.services.cross_source import PassageNliInput, record_cross_source_assessment
from apps.api.services.provenance import capture_document_version
from apps.api.services.source_independence import record_independence_assessment
from ml.provenance.identity import sha256_text
from ml.verification.cross_source import CorroborationOutcome, EvidenceStance


async def check() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    now = datetime.now(UTC)
                    version_ids = []
                    passages = []
                    for index in range(2):
                        domain = f"phase9f-{uuid4().hex}.example.com"
                        source = Source(name=f"Phase 9F source {index}", domain=domain)
                        session.add(source)
                        await session.flush()
                        document = Document(source_id=source.id, url=f"https://{domain}/story")
                        session.add(document)
                        await session.flush()
                        content = (
                            f"Authorized placeholder story from publisher {index}. "
                            f"Independent origins are not assumed in this experiment. " * 4
                        )
                        version = await capture_document_version(
                            session, document_id=document.id, text=content, retrieved_at=now
                        )
                        passage = DocumentPassage(
                            document_version_id=version.id,
                            ordinal=0,
                            start_offset=0,
                            end_offset=len(content),
                            text=content,
                            passage_sha256=sha256_text(content),
                        )
                        session.add(passage)
                        await session.flush()
                        version_ids.append(version.id)
                        passages.append(
                            PassageNliInput(
                                passage_id=passage.id,
                                stance=EvidenceStance.ENTAILMENT,
                                confidence=0.96,
                                nli_accepted=True,
                                admissible=True,
                            )
                        )
                    independence = await record_independence_assessment(
                        session, version_ids=version_ids, assessed_at=now
                    )
                    assert independence.family_count == 2
                    result = await record_cross_source_assessment(
                        session,
                        claim="A synthetic claim for transactional corroboration checks.",
                        independence_assessment_id=independence.id,
                        passages=tuple(passages),
                        assessed_at=now,
                    )
                    assert result.outcome == CorroborationOutcome.MULTI_FAMILY_SUPPORT_UNVERIFIED
                    assert result.independence_status == "NOT_ESTABLISHED"
                    evidence_rows = (
                        await session.scalars(
                            select(CrossSourceEvidence).where(
                                CrossSourceEvidence.assessment_id == result.id
                            )
                        )
                    ).all()
                    assert len(evidence_rows) == 2
                    print("Phase 9F PostgreSQL transactional smoke test passed")
            finally:
                await transaction.rollback()
                print("Rolled back the smoke-test transaction")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check())

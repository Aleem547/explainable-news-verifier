"""Phase 9F service validation and transaction boundaries without PostgreSQL."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from apps.api.db.models.cross_source_assessment import CrossSourceAssessment
from apps.api.db.models.cross_source_evidence import CrossSourceEvidence
from apps.api.db.models.document_context_assessment import DocumentContextAssessment
from apps.api.db.models.document_passage import DocumentPassage
from apps.api.db.models.document_version import DocumentVersion
from apps.api.db.models.independence_assessment import IndependenceAssessment
from apps.api.services.cross_source import PassageNliInput, record_cross_source_assessment
from ml.provenance.identity import sha256_text
from ml.verification.cross_source import EvidenceStance

NOW = datetime(2026, 10, 8, tzinfo=UTC)
A, B = UUID(int=1), UUID(int=2)
PA, PB = UUID(int=11), UUID(int=12)
CLAIM = "A synthetic fact-checking statement."


@dataclass
class FakeScalarResult:
    rows: list[object]

    def all(self) -> list[object]:
        return self.rows


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.independence = SimpleNamespace(
            id=UUID(int=90),
            assessed_at=NOW - timedelta(hours=1),
            family_count=2,
            version_ids=[str(A), str(B)],
            families=[[str(A)], [str(B)]],
        )
        self.rows: dict[tuple[type[object], UUID], object] = {
            (IndependenceAssessment, UUID(int=90)): self.independence,
        }
        for version_id, passage_id in ((A, PA), (B, PB)):
            text = "A complete stored content snapshot, not discovery metadata."
            self.rows[(DocumentVersion, version_id)] = SimpleNamespace(
                id=version_id,
                content_text=text,
                content_sha256=sha256_text(text),
                retrieved_at=NOW - timedelta(hours=2),
            )
            self.rows[(DocumentPassage, passage_id)] = SimpleNamespace(
                id=passage_id,
                document_version_id=version_id,
                start_offset=0,
                end_offset=len(text),
                text=text,
                passage_sha256=sha256_text(text),
            )

    async def get(self, cls: type[object], key: UUID) -> object | None:
        return self.rows.get((cls, key))

    async def scalars(self, statement: object) -> FakeScalarResult:
        return FakeScalarResult([])

    def add(self, item: object) -> None:
        self.added.append(item)
        if isinstance(item, CrossSourceAssessment):
            item.id = uuid4()

    async def flush(self) -> None:
        pass


def inputs() -> tuple[PassageNliInput, ...]:
    return tuple(
        PassageNliInput(
            passage_id=pid,
            stance=EvidenceStance.ENTAILMENT,
            confidence=0.95,
            nli_accepted=True,
            admissible=True,
        )
        for pid in (PA, PB)
    )


def invoke(session: FakeSession, rows: tuple[PassageNliInput, ...] | None = None):
    return asyncio.run(
        record_cross_source_assessment(
            session,  # type: ignore[arg-type]
            claim=CLAIM,
            independence_assessment_id=UUID(int=90),
            passages=rows if rows is not None else inputs(),
            assessed_at=NOW,
        )
    )


def test_service_records_passage_evidence_without_commit() -> None:
    session = FakeSession()
    assessment = invoke(session)
    assert assessment.outcome == "MULTI_FAMILY_SUPPORT_UNVERIFIED"
    assert assessment.independence_status == "NOT_ESTABLISHED"
    assert assessment.decisive_count == 2
    rows = [item for item in session.added if isinstance(item, CrossSourceEvidence)]
    assert {item.passage_id for item in rows} == {PA, PB}
    assert session.commits == 0


def test_out_of_assessment_passage_rejected() -> None:
    session = FakeSession()
    passage = session.rows[(DocumentPassage, PA)]
    passage.document_version_id = UUID(int=123)  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="outside the independence"):
        invoke(session, inputs()[:1])
    assert not session.added


def test_tampered_snapshot_rejected() -> None:
    session = FakeSession()
    version = session.rows[(DocumentVersion, A)]
    version.content_text = "Changed"  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="SHA-256"):
        invoke(session, inputs()[:1])
    assert not session.added


def test_tampered_passage_offset_rejected() -> None:
    session = FakeSession()
    passage = session.rows[(DocumentPassage, PA)]
    passage.start_offset = 1  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="Passage offsets"):
        invoke(session, inputs()[:1])
    assert not session.added


def test_future_independence_assessment_rejected() -> None:
    session = FakeSession()
    session.independence.assessed_at = NOW + timedelta(days=1)
    with pytest.raises(ValueError, match="future independence"):
        invoke(session)


def test_duplicate_input_passage_rejected() -> None:
    session = FakeSession()
    with pytest.raises(ValueError, match="Duplicate passage"):
        invoke(session, (inputs()[0], inputs()[0]))


def test_context_must_match_exact_claim() -> None:
    session = FakeSession()
    ctx_id = UUID(int=222)
    session.rows[(DocumentContextAssessment, ctx_id)] = SimpleNamespace(
        document_version_id=A,
        assessed_at=NOW,
        claim_sha256=sha256_text("Other claim"),
        reference_at=None,
        temporal_relation="BEFORE_REFERENCE",
        freshness_status="NOT_REQUESTED",
    )
    test_row = PassageNliInput(
        passage_id=PA,
        stance=EvidenceStance.ENTAILMENT,
        confidence=0.99,
        nli_accepted=True,
        admissible=True,
        context_assessment_id=ctx_id,
    )
    with pytest.raises(ValueError, match="exact claim"):
        invoke(session, (test_row,))
    assert not session.added


def test_missing_passage_does_not_create_discovery_evidence() -> None:
    session = FakeSession()
    test_row = PassageNliInput(
        passage_id=UUID(int=555),
        stance=EvidenceStance.ENTAILMENT,
        confidence=0.99,
        nli_accepted=True,
        admissible=True,
    )
    with pytest.raises(ValueError, match="does not exist"):
        invoke(session, (test_row,))
    assert not session.added


def test_unknown_model_run_cannot_be_cited() -> None:
    session = FakeSession()
    row = PassageNliInput(
        passage_id=PA,
        stance=EvidenceStance.ENTAILMENT,
        confidence=0.99,
        nli_accepted=True,
        admissible=True,
        model_run_id=UUID(int=987),
    )
    with pytest.raises(ValueError, match="model run"):
        invoke(session, (row,))
    assert not session.added


def test_model_provenance_gap_reported() -> None:
    session = FakeSession()
    result = invoke(session)
    assert "NLI_MODEL_PROVENANCE_INCOMPLETE" in result.warnings
    assert result.confidence_threshold == 0.90


def test_matching_context_is_accepted_and_outdated_evidence_is_reviewed() -> None:
    session = FakeSession()
    ctx_id = UUID(int=221)
    session.rows[(DocumentContextAssessment, ctx_id)] = SimpleNamespace(
        document_version_id=A,
        assessed_at=NOW - timedelta(minutes=2),
        claim_sha256=sha256_text(CLAIM),
        reference_at=None,
        temporal_relation="BEFORE_REFERENCE",
        freshness_status="OLDER_THAN_WINDOW",
    )
    row = PassageNliInput(
        passage_id=PA,
        stance=EvidenceStance.ENTAILMENT,
        confidence=0.99,
        nli_accepted=True,
        admissible=True,
        context_assessment_id=ctx_id,
    )
    result = invoke(session, (row,))
    assert result.outcome == "NO_DECISIVE_EVIDENCE"
    assert "TEMPORAL_REVIEW_REQUIRED" in result.warnings


def test_context_cannot_be_from_future() -> None:
    session = FakeSession()
    ctx_id = UUID(int=221)
    session.rows[(DocumentContextAssessment, ctx_id)] = SimpleNamespace(
        document_version_id=A,
        assessed_at=NOW + timedelta(seconds=1),
        claim_sha256=sha256_text(CLAIM),
        reference_at=None,
        temporal_relation="BEFORE_REFERENCE",
        freshness_status="NOT_REQUESTED",
    )
    row = PassageNliInput(
        passage_id=PA,
        stance=EvidenceStance.ENTAILMENT,
        confidence=0.99,
        nli_accepted=True,
        admissible=True,
        context_assessment_id=ctx_id,
    )
    with pytest.raises(ValueError, match="after corroboration"):
        invoke(session, (row,))
    assert not session.added


def test_mismatched_independence_membership_is_rejected() -> None:
    session = FakeSession()
    session.independence.families = [[str(A)], [str(UUID(int=202))]]
    with pytest.raises(ValueError, match="membership"):
        invoke(session)
    assert not session.added

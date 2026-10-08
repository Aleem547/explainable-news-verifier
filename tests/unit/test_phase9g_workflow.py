"""Phase 9G orchestration contracts using deterministic stand-ins, not live ML."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from apps.api.db.models.document import Document
from apps.api.db.models.document_passage import DocumentPassage
from apps.api.db.models.document_version import DocumentVersion
from apps.api.db.models.source import Source
from apps.api.schemas.multisource import MultiSourceAssessmentRequest
from apps.api.services import multisource
from ml.provenance.identity import sha256_text

NOW = datetime(2026, 10, 8, tzinfo=UTC)
A, B = UUID(int=1), UUID(int=2)
PA, PB = UUID(int=11), UUID(int=12)


class FakeDistribution:
    def __init__(self, stance: str = "ENTAILMENT", confidence: float = 0.96):
        self.stance = stance
        self.confidence = confidence

    def checked(self) -> "FakeDistribution":
        return self

    def top_label(self) -> tuple[str, float]:
        return self.stance, self.confidence


class FakePredictor:
    def __init__(self, results: list[FakeDistribution] | None = None):
        self.results = results
        self.calls = 0

    def predict(self, claim: str, evidence_texts: list[str]) -> list[FakeDistribution]:
        self.calls += 1
        if self.results is not None:
            return self.results
        return [FakeDistribution() for _ in evidence_texts]


class FakeResult:
    def __init__(self, rows: list[object]):
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class FakeSession:
    def __init__(self):
        self.mapping: dict[tuple[type[object], UUID], object] = {}
        self.audit: list[object] = []
        self.commits = 0
        for index, (version_id, passage_id) in enumerate(((A, PA), (B, PB))):
            doc_id, source_id = UUID(int=100 + index), UUID(int=200 + index)
            text = "The Eiffel Tower stands in Paris. Synthetic evidence text. " * (index + 1)
            self.mapping[(DocumentPassage, passage_id)] = SimpleNamespace(
                id=passage_id,
                document_version_id=version_id,
                start_offset=0,
                end_offset=len(text),
                text=text,
                passage_sha256=sha256_text(text),
            )
            self.mapping[(DocumentVersion, version_id)] = SimpleNamespace(
                id=version_id,
                document_id=doc_id,
                content_text=text,
                content_sha256=sha256_text(text),
                retrieved_at=NOW - timedelta(days=2),
                original_url=f"https://source{index}.example/story",
            )
            self.mapping[(Document, doc_id)] = SimpleNamespace(id=doc_id, source_id=source_id)
            self.mapping[(Source, source_id)] = SimpleNamespace(
                id=source_id, domain=f"source{index}.example"
            )

    async def get(self, cls: type[object], key: UUID) -> object | None:
        return self.mapping.get((cls, key))

    async def scalars(self, stmt: object) -> FakeResult:
        return FakeResult(self.audit)


def request() -> MultiSourceAssessmentRequest:
    return MultiSourceAssessmentRequest(
        claim="The Eiffel Tower is in Paris",
        passage_ids=[PA, PB],
        reference_at=NOW,
        max_age_days=30,
    )


def set_stubs(monkeypatch: pytest.MonkeyPatch, session: FakeSession) -> list[object]:
    observed: list[object] = []

    async def independence(db: object, **kw: object) -> SimpleNamespace:
        observed.append(("independence", kw))
        return SimpleNamespace(id=UUID(int=500), warnings=["INDEPENDENCE_NOT_PROVEN"])

    async def context(db: object, **kw: object) -> SimpleNamespace:
        observed.append(("context", kw))
        version_id = kw["document_version_id"]
        return SimpleNamespace(
            id=UUID(int=600 + (1 if version_id == A else 2)),
            temporal_relation="BEFORE_REFERENCE",
            freshness_status="WITHIN_WINDOW",
            metadata_flags=["MATCHED_FETCH_OBSERVATION"],
        )

    async def corroboration(db: object, **kw: object) -> SimpleNamespace:
        observed.append(("corroboration", kw))
        rows = kw["passages"]
        session.audit = [
            SimpleNamespace(
                passage_id=row.passage_id,
                family_id=UUID(int=1000 + idx),
                stance=row.stance.value,
                nli_confidence=row.confidence,
                decision="ELIGIBLE" if row.admissible else "ADMISSIBILITY_BLOCKED",
            )
            for idx, row in enumerate(rows)
        ]
        return SimpleNamespace(
            id=UUID(int=900),
            claim_sha256=sha256_text("The Eiffel Tower is in Paris"),
            outcome="MULTI_FAMILY_SUPPORT_UNVERIFIED",
            independence_status="NOT_ESTABLISHED",
            supporting_families=["a", "b"],
            refuting_families=[],
            decisive_count=2,
            warnings=["NLI_MODEL_PROVENANCE_INCOMPLETE"],
        )

    monkeypatch.setattr(multisource, "record_independence_assessment", independence)
    monkeypatch.setattr(multisource, "assess_document_context", context)
    monkeypatch.setattr(multisource, "record_cross_source_assessment", corroboration)
    return observed


def test_orchestrates_exact_versions_with_audited_context(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    observed = set_stubs(monkeypatch, session)
    model = FakePredictor()
    report = asyncio.run(
        multisource.evaluate_captured_evidence(
            session,
            request(),
            predictor=model,
            assessed_at=NOW,  # type: ignore[arg-type]
        )
    )
    assert model.calls == 1
    assert [step[0] for step in observed] == ["independence", "context", "context", "corroboration"]
    assert len(report.evidence) == 2
    assert report.independent_corroboration_established is False
    assert "NLI_MODEL_PROVENANCE_INCOMPLETE" in report.warnings
    assert report.evidence[0].passage_sha256 == sha256_text(report.evidence[0].passage_text)
    assert session.commits == 0


def test_missing_passage_fails_before_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    session.mapping.pop((DocumentPassage, PA))
    set_stubs(monkeypatch, session)
    model = FakePredictor()
    with pytest.raises(ValueError, match="captured content"):
        asyncio.run(
            multisource.evaluate_captured_evidence(
                session,
                request(),
                predictor=model,
                assessed_at=NOW,  # type: ignore[arg-type]
            )
        )
    assert model.calls == 0


def test_tampered_snapshot_fails_before_inference() -> None:
    session = FakeSession()
    version = session.mapping[(DocumentVersion, A)]
    version.content_text = "TAMPERED"  # type: ignore[attr-defined]
    model = FakePredictor()
    with pytest.raises(ValueError, match="hash mismatch"):
        asyncio.run(
            multisource.evaluate_captured_evidence(
                session,
                request(),
                predictor=model,
                assessed_at=NOW,  # type: ignore[arg-type]
            )
        )
    assert model.calls == 0


def test_wrong_model_output_count_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    observed = set_stubs(monkeypatch, session)
    with pytest.raises(ValueError, match="inconsistent number"):
        asyncio.run(
            multisource.evaluate_captured_evidence(
                session,
                request(),
                predictor=FakePredictor([FakeDistribution()]),
                assessed_at=NOW,  # type: ignore[arg-type]
            )
        )
    assert not observed


def test_missing_named_subject_is_not_admitted(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    observed = set_stubs(monkeypatch, session)
    req = MultiSourceAssessmentRequest(claim="Some towers are in Paris", passage_ids=[PA, PB])
    asyncio.run(
        multisource.evaluate_captured_evidence(
            session,
            req,
            predictor=FakePredictor(),
            assessed_at=NOW,  # type: ignore[arg-type]
        )
    )
    passages = observed[-1][1]["passages"]  # type: ignore[index]
    assert all(not item.admissible for item in passages)

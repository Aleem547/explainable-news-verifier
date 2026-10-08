"""Phase 9G orchestration for captured full-text passages, never search snippets.

The caller owns the transaction. NLI loads lazily only after audited passages
are selected. The existing Phase 8 endpoint remains untouched.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from functools import lru_cache
from threading import Lock
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from apps.api.db.models.cross_source_evidence import CrossSourceEvidence
from apps.api.db.models.document import Document
from apps.api.db.models.document_context_assessment import DocumentContextAssessment
from apps.api.db.models.document_passage import DocumentPassage
from apps.api.db.models.document_version import DocumentVersion
from apps.api.db.models.source import Source
from apps.api.schemas.multisource import (
    MultiSourceAssessmentRequest,
    MultiSourceAssessmentResponse,
    MultiSourceEvidenceResponse,
)
from apps.api.services.cross_source import PassageNliInput, record_cross_source_assessment
from apps.api.services.source_context import assess_document_context
from apps.api.services.source_independence import record_independence_assessment
from ml.provenance.identity import sha256_text
from ml.verification.cross_source import EvidenceStance
from ml.verification.external_admissibility import external_subject_grounded


class MultiSourceBusyError(RuntimeError):
    """Local inference is currently occupied."""


class MultiSourceModelUnavailable(RuntimeError):
    """The frozen calibrated checkpoint cannot be loaded."""


class PredictionDistribution(Protocol):
    def checked(self) -> PredictionDistribution: ...

    def top_label(self) -> tuple[str, float]: ...


class Predictor(Protocol):
    def predict(
        self, claim: str, evidence_texts: Sequence[str]
    ) -> Sequence[PredictionDistribution]: ...


def _validated_stance(value: str) -> Literal["ENTAILMENT", "CONTRADICTION", "NEUTRAL"]:
    """Narrow the database string to the three allowed response values."""
    if value == "ENTAILMENT":
        return "ENTAILMENT"
    if value == "CONTRADICTION":
        return "CONTRADICTION"
    if value == "NEUTRAL":
        return "NEUTRAL"
    raise RuntimeError("Unexpected NLI stance in the persisted assessment")


_model_lock = Lock()
_inference_lock = Lock()


@lru_cache(maxsize=1)
def _load_model() -> Predictor:
    from ml.verification.nli_inference import CalibratedNliVerifier

    return CalibratedNliVerifier(device="cpu")


def _model_predict(claim: str, texts: list[str]) -> Sequence[PredictionDistribution]:
    if not _inference_lock.acquire(blocking=False):
        raise MultiSourceBusyError("The CPU NLI model is already running")
    try:
        with _model_lock:
            try:
                model = _load_model()
            except (ValueError, OSError, RuntimeError) as exc:
                raise MultiSourceModelUnavailable("Calibrated NLI artifacts unavailable") from exc
        return model.predict(claim, texts)
    finally:
        _inference_lock.release()


async def _predict(
    claim: str, texts: list[str], predictor: Predictor | None
) -> Sequence[PredictionDistribution]:
    # In real API requests the synchronous transformer runs off the event loop.
    if predictor is None:
        return await run_in_threadpool(_model_predict, claim, texts)
    return predictor.predict(claim, texts)


async def evaluate_captured_evidence(
    session: AsyncSession,
    request: MultiSourceAssessmentRequest,
    *,
    predictor: Predictor | None = None,
    assessed_at: datetime | None = None,
) -> MultiSourceAssessmentResponse:
    """Bind checkpoint NLI to immutable stored passages, contexts and families.

    This function does not commit or acquire web content; caller should wrap it
    in an explicit transaction, rolling back on any error.
    """
    at = assessed_at or datetime.now(UTC)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Assessment timestamp must include a timezone")

    passages: list[DocumentPassage] = []
    version_ids: set[UUID] = set()
    for passage_id in request.passage_ids:
        passage = await session.get(DocumentPassage, passage_id)
        if passage is None:
            raise ValueError("Passage ID does not reference captured content")
        version = await session.get(DocumentVersion, passage.document_version_id)
        if version is None or version.retrieved_at > at:
            raise ValueError("Snapshot missing or not yet retrieved")
        if sha256_text(version.content_text) != version.content_sha256:
            raise ValueError("Snapshot content hash mismatch")
        if not (
            0 <= passage.start_offset < passage.end_offset <= len(version.content_text)
            and version.content_text[passage.start_offset : passage.end_offset] == passage.text
            and sha256_text(passage.text) == passage.passage_sha256
        ):
            raise ValueError("Passage is not an authentic span of its stored snapshot")
        passages.append(passage)
        version_ids.add(version.id)

    if len(version_ids) < 2:
        raise ValueError("At least two distinct document snapshots are needed")
    distributions = await _predict(request.claim, [item.text for item in passages], predictor)
    if len(distributions) != len(passages):
        raise ValueError("NLI model returned an inconsistent number of predictions")

    independence = await record_independence_assessment(
        session, version_ids=sorted(version_ids, key=lambda key: key.hex), assessed_at=at
    )
    context_by_version: dict[UUID, DocumentContextAssessment] = {}
    for version_id in sorted(version_ids, key=lambda key: key.hex):
        context_by_version[version_id] = await assess_document_context(
            session,
            document_version_id=version_id,
            assessed_at=at,
            claim_text=request.claim,
            reference_at=request.reference_at,
            max_age_days=request.max_age_days,
        )

    inputs: list[PassageNliInput] = []
    for passage, raw in zip(passages, distributions, strict=True):
        probs = raw.checked()
        label, confidence = probs.top_label()
        inputs.append(
            PassageNliInput(
                passage_id=passage.id,
                stance=EvidenceStance(label),
                confidence=confidence,
                nli_accepted=label != "NEUTRAL" and confidence >= request.confidence_threshold,
                admissible=(
                    external_subject_grounded(request.claim, passage.text)
                    and "MATCHED_FETCH_OBSERVATION"
                    in context_by_version[passage.document_version_id].metadata_flags
                ),
                context_assessment_id=context_by_version[passage.document_version_id].id,
                model_run_id=None,  # No model registry mapping has been independently checked.
            )
        )
    assessment = await record_cross_source_assessment(
        session,
        claim=request.claim,
        independence_assessment_id=independence.id,
        passages=tuple(inputs),
        assessed_at=at,
        reference_at=request.reference_at,
        confidence_threshold=request.confidence_threshold,
    )
    audit_rows = (
        await session.scalars(
            select(CrossSourceEvidence).where(CrossSourceEvidence.assessment_id == assessment.id)
        )
    ).all()
    by_passage = {row.passage_id: row for row in audit_rows}
    if len(by_passage) != len(passages):
        raise RuntimeError("Persisted evidence record count mismatch")

    evidence: list[MultiSourceEvidenceResponse] = []
    for passage in passages:
        version = await session.get(DocumentVersion, passage.document_version_id)
        if version is None:
            raise RuntimeError("Missing document snapshot while rendering audit")
        document = await session.get(Document, version.document_id)
        if document is None:
            raise RuntimeError("Missing document while rendering audit")
        source = await session.get(Source, document.source_id)
        if source is None:
            raise RuntimeError("Missing source while rendering audit")
        context = context_by_version[passage.document_version_id]
        record = by_passage[passage.id]
        evidence.append(
            MultiSourceEvidenceResponse(
                passage_id=passage.id,
                document_version_id=version.id,
                family_id=record.family_id,
                publisher_domain=source.domain or "unknown",
                article_url=version.original_url,
                passage_text=passage.text,
                passage_sha256=passage.passage_sha256,
                stance=_validated_stance(record.stance),
                confidence=record.nli_confidence,
                decision=record.decision,
                temporal_relation=context.temporal_relation,
                freshness_status=context.freshness_status,
                metadata_flags=context.metadata_flags,
            )
        )
    warnings = list(
        dict.fromkeys(
            [
                *independence.warnings,
                *assessment.warnings,
                "SUBJECT_GROUNDING_IS_HEURISTIC_NOT_ENTITY_LINKING",
                "MULTISOURCE_NLI_NOT_EVALUATED_ON_EXTERNAL_GOLD_LABELS",
            ]
        )
    )
    return MultiSourceAssessmentResponse(
        assessment_id=assessment.id,
        independence_assessment_id=independence.id,
        claim=request.claim,
        claim_sha256=assessment.claim_sha256,
        outcome=assessment.outcome,
        independence_status=assessment.independence_status,
        independent_corroboration_established=False,
        provisional_supporting_families=len(assessment.supporting_families),
        provisional_refuting_families=len(assessment.refuting_families),
        decisive_evidence_count=assessment.decisive_count,
        warnings=warnings,
        evidence=evidence,
    )

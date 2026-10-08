"""Persist independent-family *diagnostics* for exact stored passages.

No external requests, live model inference, claim verdicts, or commits are made.
Caller supplies NLI results and owns the surrounding database transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models.cross_source_assessment import CrossSourceAssessment
from apps.api.db.models.cross_source_evidence import CrossSourceEvidence
from apps.api.db.models.document_context_assessment import DocumentContextAssessment
from apps.api.db.models.document_passage import DocumentPassage
from apps.api.db.models.document_version import DocumentVersion
from apps.api.db.models.independence_assessment import IndependenceAssessment
from apps.api.db.models.independence_pair import IndependencePair
from apps.api.db.models.model_run import ModelRun
from ml.provenance.identity import sha256_text
from ml.verification.cross_source import (
    EvidenceInput,
    EvidenceStance,
    assess_cross_source,
)
from ml.verification.source_context import FreshnessStatus, TemporalRelation, require_aware


@dataclass(frozen=True, slots=True)
class PassageNliInput:
    passage_id: UUID
    stance: EvidenceStance
    confidence: float
    nli_accepted: bool
    admissible: bool
    context_assessment_id: UUID | None = None
    model_run_id: UUID | None = None


async def record_cross_source_assessment(
    session: AsyncSession,
    *,
    claim: str,
    independence_assessment_id: UUID,
    passages: tuple[PassageNliInput, ...],
    assessed_at: datetime,
    reference_at: datetime | None = None,
    confidence_threshold: float = 0.90,
) -> CrossSourceAssessment:
    """Record claim-scoped evidence signals; source independence is unverified.

    Every passage is checked against an immutable captured document snapshot.
    Phase 9E's snapshot and pair decisions must be reused unchanged. Temporal
    assessments must be claim-matched and cannot be observed in the future.
    """
    require_aware(assessed_at)
    if reference_at is not None:
        require_aware(reference_at)
    if not 3 <= len(claim.strip()) <= 5000:
        raise ValueError("Claim must contain 3 to 5000 characters")
    if not 1 <= len(passages) <= 100:
        raise ValueError("Expected between 1 and 100 passages")
    if len({row.passage_id for row in passages}) != len(passages):
        raise ValueError("Duplicate passage ID in corroboration request")
    independence = await session.get(IndependenceAssessment, independence_assessment_id)
    if independence is None:
        raise ValueError("Independence assessment does not exist")
    if independence.assessed_at > assessed_at:
        raise ValueError("Cannot use a future independence assessment")
    try:
        families = tuple(tuple(UUID(item) for item in group) for group in independence.families)
        version_ids = {UUID(item) for item in independence.version_ids}
    except (TypeError, ValueError) as exc:
        raise ValueError("Corrupted independence assessment snapshot IDs") from exc
    if not families or len(families) != independence.family_count:
        raise ValueError("Independence family count does not match assessment")
    if {item for family in families for item in family} != version_ids:
        raise ValueError("Independence family membership does not match original versions")

    pairs = (
        await session.scalars(
            select(IndependencePair).where(
                IndependencePair.assessment_id == independence_assessment_id
            )
        )
    ).all()
    possible_reuse = frozenset(
        frozenset((pair.left_version_id, pair.right_version_id))
        for pair in pairs
        if pair.relationship == "POSSIBLE_TEXT_REUSE"
    )
    claim_hash = sha256_text(claim.strip())
    inputs: list[EvidenceInput] = []
    for item in passages:
        passage = await session.get(DocumentPassage, item.passage_id)
        if passage is None:
            raise ValueError("An evidence passage does not exist")
        if passage.document_version_id not in version_ids:
            raise ValueError("Evidence passage is outside the independence assessment")
        version = await session.get(DocumentVersion, passage.document_version_id)
        if version is None:
            raise ValueError("Passage document snapshot does not exist")
        if version.retrieved_at > assessed_at:
            raise ValueError("Passage document snapshot was retrieved after the assessment")
        if sha256_text(version.content_text) != version.content_sha256:
            raise ValueError("Stored document version SHA-256 mismatch")
        if not (
            0 <= passage.start_offset < passage.end_offset <= len(version.content_text)
            and version.content_text[passage.start_offset : passage.end_offset] == passage.text
            and sha256_text(passage.text) == passage.passage_sha256
        ):
            raise ValueError("Passage offsets or SHA-256 differ from the stored snapshot")
        if item.model_run_id is not None and await session.get(ModelRun, item.model_run_id) is None:
            raise ValueError("Referenced NLI model run does not exist")
        temporal: TemporalRelation | None = None
        freshness: FreshnessStatus | None = None
        if item.context_assessment_id is not None:
            context = await session.get(DocumentContextAssessment, item.context_assessment_id)
            if context is None or context.document_version_id != version.id:
                raise ValueError("Temporal context does not belong to the passage snapshot")
            if context.assessed_at > assessed_at:
                raise ValueError("Cannot use context assessed after corroboration")
            if context.claim_sha256 != claim_hash:
                raise ValueError("Temporal context was not assessed for the exact claim")
            if (context.reference_at is None) != (reference_at is None) or (
                context.reference_at is not None
                and reference_at is not None
                and context.reference_at.astimezone(UTC) != reference_at.astimezone(UTC)
            ):
                raise ValueError("Temporal context reference time does not match request")
            temporal = TemporalRelation(context.temporal_relation)
            freshness = FreshnessStatus(context.freshness_status)
        inputs.append(
            EvidenceInput(
                version_id=passage.document_version_id,
                passage_id=passage.id,
                stance=item.stance,
                confidence=item.confidence,
                nli_accepted=item.nli_accepted,
                admissible=item.admissible,
                temporal_relation=temporal,
                freshness_status=freshness,
            )
        )

    summary = assess_cross_source(
        families=families,
        evidence=tuple(inputs),
        possible_reuse_pairs=possible_reuse,
        confidence_threshold=confidence_threshold,
    )
    assessment = CrossSourceAssessment(
        independence_assessment_id=independence_assessment_id,
        claim_sha256=claim_hash,
        assessed_at=assessed_at,
        reference_at=reference_at,
        rule_version=summary.rule_version,
        confidence_threshold=confidence_threshold,
        input_count=len(inputs),
        decisive_count=summary.decisive_count,
        outcome=summary.outcome.value,
        independence_status=summary.independence_status,
        supporting_families=[str(item) for item in summary.supporting_family_ids],
        refuting_families=[str(item) for item in summary.refuting_family_ids],
        mixed_families=[str(item) for item in summary.mixed_family_ids],
        warnings=(
            list(summary.warnings)
            + (
                ["NLI_MODEL_PROVENANCE_INCOMPLETE"]
                if any(item.model_run_id is None for item in passages)
                else []
            )
        ),
    )
    session.add(assessment)
    await session.flush()
    by_passage = {item.passage_id: item for item in passages}
    for finding in summary.findings:
        raw = by_passage[finding.passage_id]
        session.add(
            CrossSourceEvidence(
                assessment_id=assessment.id,
                document_version_id=finding.version_id,
                passage_id=finding.passage_id,
                context_assessment_id=raw.context_assessment_id,
                model_run_id=raw.model_run_id,
                family_id=finding.family_id,
                stance=finding.stance.value,
                nli_confidence=finding.confidence,
                nli_accepted=raw.nli_accepted,
                admissible=raw.admissible,
                decision=finding.decision.value,
            )
        )
    await session.flush()
    return assessment

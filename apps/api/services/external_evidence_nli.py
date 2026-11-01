"""Phase 13D.5: bounded, read-only NLI over audited external article passages.

Reuses the *existing* calibrated DeBERTa inference lock/checkpoint. Passage-level
NLI scores are not truth probabilities or independent source corroboration.
No API route, HTTP fetch, database write, or evidence-acceptance verdict here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Protocol
from uuid import UUID
from ml.verification.paragraph_inputs import (
    ParagraphInput, ParagraphSelection, AuditedParagraphInput, validate_paragraph_selection,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from apps.api.services.external_passage_retrieval import ExternalPassageCandidate
    from ml.verification.external_source_dependencies import ReportedDependency


class ExternalNliError(ValueError):
    """Invalid or stale evidence, unbounded input, or invalid model output."""


class NliPredictor(Protocol):
    def predict(self, claim: str, evidence_texts: Sequence[str]) -> Sequence[object]: ...


@dataclass(frozen=True, slots=True)
class ExternalNliPassage:
    passage_id: UUID
    document_version_id: UUID
    source_id: UUID
    publisher_domain: str
    article_url: str
    passage_text: str
    passage_sha256: str
    retrieved_at: datetime
    lexical_relevance_score: float
    dependency_risk_family: int
    duplicate_group: int
    nli_label: str
    entailment: float
    contradiction: float
    neutral: float
    nli_confidence: float
    nli_threshold_passed: bool
    # NLI assessment does NOT establish this source is trustworthy or independent.
    nli_evaluated: bool = True
    independently_verified: bool = False
    independent_corroboration_established: bool = False
    paragraph_input: ParagraphInput | None = None
    input_pair_tokens: int | None = None
    model_max_length: int | None = None

    @property
    def input_kind(self) -> str:
        return "DERIVED_PARAGRAPH" if self.paragraph_input is not None else "STORED_PASSAGE"


@dataclass(frozen=True, slots=True)
class ExternalNliReport:
    claim: str
    assessed_at: datetime
    nli_threshold: float
    evidence: tuple[ExternalNliPassage, ...]
    dependency_risk_family_count: int
    exact_duplicate_count: int
    possible_near_duplicate_count: int
    warnings: tuple[str, ...] = (
        "NLI_LABEL_IS_A_TEXTUAL_RELATION_NOT_CLAIM_TRUTH",
        "MODEL_CALIBRATION_WAS_NOT_FITTED_ON_EXTERNAL_NEWS_EVIDENCE",
        "DEPENDENCY_RISK_FAMILIES_ARE_NOT_PROOF_OF_EDITORIAL_INDEPENDENCE",
        "DECISIVE_NLI_THRESHOLDS_DO_NOT_ESTABLISH_CORROBORATION",
    )
    independence_status: str = "NOT_ESTABLISHED"
    independent_corroboration_established: bool = False
    independently_verified: bool = False
    paragraph_selection: ParagraphSelection | None = None


def validate_nli_input_bindings(report: ExternalNliReport) -> None:
    """Replay derived text/identity bindings before any downstream vote."""
    selection = report.paragraph_selection
    if selection is None:
        if any(row.paragraph_input is not None or row.input_pair_tokens is not None
               or row.model_max_length is not None for row in report.evidence):
            raise ExternalNliError("paragraph_metadata_without_selection")
        return
    try:
        validate_paragraph_selection(selection)
    except ValueError as exc:
        raise ExternalNliError("invalid_paragraph_selection") from exc
    expected = {p.context_id: p for p in selection.inputs}
    if len(report.evidence) != len(expected) or {r.passage_id for r in report.evidence} != set(expected):
        raise ExternalNliError("paragraph_report_input_coverage_mismatch")
    if len({row.model_max_length for row in report.evidence}) != 1:
        raise ExternalNliError("paragraph_model_budget_mismatch")
    for row in report.evidence:
        paragraph = expected[row.passage_id]
        if (row.paragraph_input != paragraph
                or row.document_version_id != paragraph.document_version_id
                or row.source_id != paragraph.source_id
                or row.publisher_domain != paragraph.publisher_domain
                or row.article_url != paragraph.original_url
                or row.retrieved_at != paragraph.retrieved_at
                or row.lexical_relevance_score != paragraph.lexical_relevance_score
                or row.passage_text != paragraph.text or row.passage_sha256 != paragraph.sha256
                or paragraph.parent.fetch_observed_at > report.assessed_at
                or type(row.input_pair_tokens) is not int
                or type(row.model_max_length) is not int
                or not 16 <= row.model_max_length <= 4096
                or not 0 < row.input_pair_tokens <= row.model_max_length):
            raise ExternalNliError("paragraph_report_binding_mismatch")


def _probabilities(raw: object) -> tuple[str, float, float, float, float]:
    """Validate calibrated model distribution without trusting arbitrary labels."""
    if hasattr(raw, "checked"):
        raw = raw.checked()
    try:
        values = (raw.entailment, raw.contradiction, raw.neutral)
    except AttributeError as exc:
        raise ExternalNliError("nli_output_missing_probabilities") from exc
    if not all(
        isinstance(p, (int, float)) and not isinstance(p, bool)
        and math.isfinite(p) and 0 <= p <= 1
        for p in values
    ) or not math.isclose(sum(values), 1.0, abs_tol=1e-4):
        raise ExternalNliError("invalid_nli_probability_distribution")
    e, c, n = (float(x) for x in values)
    label, confidence = max(
        (("ENTAILMENT", e), ("CONTRADICTION", c), ("NEUTRAL", n)),
        key=lambda item: item[1],
    )
    return label, confidence, e, c, n


def _validate_request(claim: str, candidates: Sequence[object], threshold: float, at: datetime) -> None:
    if not isinstance(claim, str) or not 3 <= len(claim.strip()) <= 2000:
        raise ExternalNliError("invalid_claim_length")
    if not isinstance(candidates, (tuple, list)) or not 2 <= len(candidates) <= 20:
        raise ExternalNliError("invalid_candidate_batch")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not math.isfinite(threshold) or not 0.5 <= threshold <= 1:
        raise ExternalNliError("invalid_nli_threshold")
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise ExternalNliError("assessment_timestamp_must_be_aware")
    ids = [getattr(c, "passage_id", None) for c in candidates]
    versions = [getattr(c, "document_version_id", None) for c in candidates]
    if not all(isinstance(x, UUID) for x in ids + versions) or len(set(ids)) != len(ids) or len(set(versions)) < 2:
        raise ExternalNliError("requires_distinct_passages_and_versions")
    texts = [getattr(c, "passage_text", None) for c in candidates]
    if any(not isinstance(t, str) or not 1 <= len(t) <= 20_000 for t in texts) or sum(map(len, texts)) > 120_000:
        raise ExternalNliError("evidence_text_budget_exceeded")
    for c in candidates:
        if any(getattr(c, flag, None) is not False for flag in (
            "independently_verified", "nli_evaluated", "independent_corroboration_established"
        )):
            raise ExternalNliError("candidate_already_assessed")
        if sha256(c.passage_text.encode("utf-8")).hexdigest() != getattr(c, "passage_sha256", None):
            raise ExternalNliError("tampered_candidate_text")


def build_external_nli_report(
    *,
    claim: str,
    audits: Sequence[object],
    normalization: object,
    dependencies: object,
    predictions: Sequence[object],
    nli_threshold: float = 0.90,
    assessed_at: datetime,
    paragraph_selection: ParagraphSelection | None = None,
    input_pair_tokens: Sequence[int] | None = None,
    model_max_length: int | None = None,
) -> ExternalNliReport:
    """Pure validation and report construction (the predictor never runs here).

    Database audit, normalization, dependencies, and predictions must originate
    from their corresponding validated services. This function also checks their
    identities match exactly, and fails closed instead of silently dropping rows.
    """
    if not isinstance(audits, (tuple, list)):
        raise ExternalNliError("invalid_audit_batch")
    candidates = [getattr(a, "candidate", None) for a in audits]
    _validate_request(claim, candidates, nli_threshold, assessed_at)
    if paragraph_selection is not None:
        try:
            validate_paragraph_selection(paragraph_selection)
        except ValueError as exc:
            raise ExternalNliError("invalid_paragraph_selection") from exc
        if (tuple(candidates) != paragraph_selection.inputs
                or any(type(a) is not AuditedParagraphInput for a in audits)
                or not isinstance(input_pair_tokens, (tuple, list))
                or len(input_pair_tokens) != len(candidates)
                or type(model_max_length) is not int or not 16 <= model_max_length <= 4096
                or any(type(n) is not int or not 0 < n <= model_max_length for n in input_pair_tokens)):
            raise ExternalNliError("paragraph_input_or_token_binding_mismatch")
    elif (any(isinstance(c, ParagraphInput) for c in candidates)
          or input_pair_tokens is not None or model_max_length is not None):
        raise ExternalNliError("derived_inputs_require_selection_and_token_binding")
    ids = {c.passage_id for c in candidates}
    versions = {c.document_version_id for c in candidates}
    for audit in audits:
        if getattr(audit, "traceable", None) is not True or any(
            getattr(audit, field, None) is not False for field in (
                "nli_evaluated", "independently_verified", "independent_corroboration_established"
            )
        ):
            raise ExternalNliError("unaudited_or_preassessed_passage")
        if not isinstance(getattr(audit, "fetch_observation_id", None), UUID):
            raise ExternalNliError("missing_fetch_observation")
        if (audit.candidate.retrieved_at > assessed_at
                or getattr(audit, "fetch_observed_at", None) is None
                or audit.fetch_observed_at.tzinfo is None
                or audit.fetch_observed_at.utcoffset() is None
                or audit.fetch_observed_at > assessed_at):
            raise ExternalNliError("future_or_invalid_observation_time")

    if (getattr(dependencies, "independence_status", None) != "NOT_ESTABLISHED"
            or getattr(dependencies, "independent_corroboration_established", None) is not False
            or getattr(dependencies, "independently_verified", None) is not False):
        raise ExternalNliError("invalid_dependency_status")
    families = getattr(dependencies, "risk_families", None)
    if not isinstance(families, tuple) or not families:
        raise ExternalNliError("missing_dependency_risk_families")
    version_to_family: dict[UUID, int] = {}
    for index, family in enumerate(families, start=1):
        if not isinstance(family, tuple) or not family:
            raise ExternalNliError("invalid_dependency_family")
        for version in family:
            if not isinstance(version, UUID) or version in version_to_family:
                raise ExternalNliError("duplicate_dependency_version")
            version_to_family[version] = index
    if set(version_to_family) != versions or set(getattr(dependencies, "version_ids", ())) != versions:
        raise ExternalNliError("dependency_versions_mismatch")

    if (getattr(normalization, "input_count", None) != len(candidates)
            or getattr(normalization, "independent_corroboration_established", None) is not False):
        raise ExternalNliError("invalid_normalization_report")
    groups = getattr(normalization, "groups", None)
    if not isinstance(groups, tuple):
        raise ExternalNliError("missing_normalization_groups")
    by_passage: dict[UUID, int] = {}
    for index, group in enumerate(groups, start=1):
        for member in getattr(group, "members", ()):
            normalized_candidate = getattr(member, "candidate", None)
            passage_id = getattr(normalized_candidate, "passage_id", None)
            if passage_id in by_passage or passage_id not in ids:
                raise ExternalNliError("duplicate_or_foreign_normalized_passage")
            # Compare text/URL/version identity as well as passage ID.
            actual = next(c for c in candidates if c.passage_id == passage_id)
            if (normalized_candidate.document_version_id != actual.document_version_id
                    or normalized_candidate.source_id != actual.source_id
                    or normalized_candidate.passage_text != actual.passage_text
                    or normalized_candidate.original_url != actual.original_url):
                raise ExternalNliError("normalized_evidence_mismatch")
            by_passage[passage_id] = index
    if set(by_passage) != ids:
        raise ExternalNliError("normalization_candidate_coverage_mismatch")

    if not isinstance(predictions, (tuple, list)) or len(predictions) != len(candidates):
        raise ExternalNliError("nli_output_count_mismatch")
    evidence = []
    for index, (audit, raw) in enumerate(zip(audits, predictions, strict=True)):
        candidate = audit.candidate
        label, confidence, e, c, n = _probabilities(raw)
        evidence.append(ExternalNliPassage(
            passage_id=candidate.passage_id,
            document_version_id=candidate.document_version_id,
            source_id=candidate.source_id,
            publisher_domain=candidate.publisher_domain,
            article_url=candidate.original_url,
            passage_text=candidate.passage_text,
            passage_sha256=candidate.passage_sha256,
            retrieved_at=candidate.retrieved_at,
            lexical_relevance_score=candidate.lexical_relevance_score,
            dependency_risk_family=version_to_family[candidate.document_version_id],
            duplicate_group=by_passage[candidate.passage_id],
            nli_label=label,
            entailment=e,
            contradiction=c,
            neutral=n,
            nli_confidence=confidence,
            nli_threshold_passed=(label != "NEUTRAL" and confidence >= nli_threshold),
            paragraph_input=candidate if paragraph_selection is not None else None,
            input_pair_tokens=input_pair_tokens[index] if input_pair_tokens is not None else None,
            model_max_length=model_max_length,
        ))
    return ExternalNliReport(
        claim=claim.strip(), assessed_at=assessed_at,
        nli_threshold=float(nli_threshold), evidence=tuple(evidence),
        dependency_risk_family_count=len(families),
        exact_duplicate_count=normalization.exact_duplicate_count,
        possible_near_duplicate_count=normalization.possible_near_duplicate_count,
        paragraph_selection=paragraph_selection,
    )


async def assess_external_evidence_nli(
    session: AsyncSession,
    *,
    claim: str,
    candidates: Sequence[ExternalPassageCandidate],
    predictor: NliPredictor | None = None,
    assessed_at: datetime | None = None,
    nli_threshold: float = 0.90,
    reported_links: Sequence[ReportedDependency] = (),
) -> ExternalNliReport:
    """Read-only D.3 → D.2 → D.4 → calibrated DeBERTa, in input order.

    Call only with already-fetched, stored external passages. The existing model
    lock is shared with the multisource endpoint. No independent corroboration
    decision is made here (that is Phases 13D.6-7).

    reported_links are trusted server/operator inputs for conservative risk
    grouping, not authenticated declarations of independent reporting. They
    must not be populated directly from unreviewed public request fields.
    """
    at = assessed_at or datetime.now(UTC)
    _validate_request(claim, candidates, nli_threshold, at)
    if not isinstance(reported_links, (tuple, list)) or len(reported_links) > 100:
        raise ExternalNliError("invalid_reported_dependency_batch")

    # Import lazily: unit-only builds should not initialize SQLAlchemy or torch.
    from apps.api.services.external_evidence_normalization import normalize_and_group_external_evidence
    from apps.api.services.external_evidence_provenance import audit_external_passage_provenance
    from apps.api.services.external_source_independence import audit_external_source_dependencies
    from starlette.concurrency import run_in_threadpool

    audits = await audit_external_passage_provenance(session, candidates)
    normalized = normalize_and_group_external_evidence(list(candidates))
    # Optional server-side dependency declarations can conservatively combine
    # reuse risks. They never establish independence. Preserve the legacy
    # empty-input call contract for existing integrations/test seams.
    if reported_links:
        risks = await audit_external_source_dependencies(
            session, list(candidates), assessed_at=at, reported_links=tuple(reported_links),
        )
    else:
        risks = await audit_external_source_dependencies(session, list(candidates), assessed_at=at)
    texts = [c.passage_text for c in candidates]  # original exact snapshot spans
    if predictor is None:
        from apps.api.services.multisource import _model_predict
        predictions = await run_in_threadpool(_model_predict, claim.strip(), texts)
    else:
        predictions = await run_in_threadpool(predictor.predict, claim.strip(), texts)
    report = build_external_nli_report(
        claim=claim, audits=audits, normalization=normalized,
        dependencies=risks, predictions=predictions,
        nli_threshold=nli_threshold, assessed_at=at,
    )
    if reported_links:
        # The dependency audit did no NLI itself; this wrapper has now run NLI.
        risk_warnings = set(risks.warnings) - {"NO_NLI_OR_TRUTH_ASSESSMENT"}
        report = replace(report, warnings=tuple(sorted(set(report.warnings) | risk_warnings | {
            "REPORTED_DEPENDENCIES_ARE_UNAUTHENTICATED_DECLARATIONS",
        })))
    return report

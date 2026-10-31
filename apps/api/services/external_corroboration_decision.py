"""Phase 13D.7: conservative decision over audited external evidence.

No database, network, or model execution. Upstream source-dependency risk
families do not prove editorial independence; this module therefore NEVER
reports independently established corroboration on the current contract.
A future positive decision requires a separately audited independence proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from apps.api.services.external_evidence_agreement import (
    EvidenceAgreementError,
    ExternalAgreementReport,
    analyze_external_evidence_agreement,
)
from apps.api.services.external_evidence_nli import ExternalNliReport
from apps.api.services.external_independence_review import (
    ExternalIndependenceReview,
    ExternalIndependenceReviewError,
    build_external_independence_review,
)
from apps.api.services.external_reporting_origin_audit import (
    ReportingOriginAudit,
    ReportingOriginAuditError,
    ReportingOriginAuditSummary,
    summarize_reporting_origin_audit,
)

DECISION_POLICY_VERSION = "phase3.2-grounded-conservative-v1"
ORIGIN_AUDIT_DECISION_POLICY_VERSION = "phase3.2-grounded-origin-audit-decision-v1"


class CorroborationDecisionError(ValueError):
    """A report is untrusted, stale, incomplete, or internally inconsistent."""


class ExternalEvidenceVerdict(StrEnum):
    """Evidence alignment ONLY; none is a factual truth verdict."""

    PROVISIONAL_SUPPORT = "PROVISIONAL_SUPPORT"
    PROVISIONAL_REFUTATION = "PROVISIONAL_REFUTATION"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class ExternalCorroborationDecision:
    claim: str
    assessed_at: datetime
    evidence_verdict: ExternalEvidenceVerdict
    evidence_passage_ids: tuple[UUID, ...]
    supporting_passage_ids: tuple[UUID, ...]
    refuting_passage_ids: tuple[UUID, ...]
    inconclusive_passage_ids: tuple[UUID, ...]
    provisional_unit_count: int
    supporting_unit_count: int
    refuting_unit_count: int
    mixed_unit_count: int
    inconclusive_unit_count: int
    source_risk_family_count: int
    explanation_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    policy_version: str = DECISION_POLICY_VERSION
    independence_status: str = "NOT_ESTABLISHED"
    independent_corroboration_established: bool = False
    independently_verified: bool = False
    origin_review_pair_count: int = 0
    origin_review_packet_sha256: str | None = None
    origin_audit: ReportingOriginAuditSummary | None = None
    subject_excluded_decisive_passage_ids: tuple[UUID, ...] = ()
    decisive_admissibility_policy_version: str | None = None
    scope_excluded_decisive_passages: tuple[tuple[UUID, tuple[str, ...]], ...] = ()


def decide_external_corroboration(
    *,
    nli_report: ExternalNliReport,
    agreement_report: ExternalAgreementReport,
    independence_review: ExternalIndependenceReview | None = None,
    reporting_origin_audit: ReportingOriginAudit | None = None,
) -> ExternalCorroborationDecision:
    """Fail-closed read-only conclusion using the verified 13D.6 agreement.

    Rebuild Phase 13D.6 from the matching NLI report instead of trusting any
    caller-supplied counts, labels, warnings, or flags. Passing this check does
    not validate the real-world reporting origin or editorial independence.
    """
    if not isinstance(nli_report, ExternalNliReport):
        raise CorroborationDecisionError("invalid_nli_report")
    if not isinstance(agreement_report, ExternalAgreementReport):
        raise CorroborationDecisionError("invalid_agreement_report")
    try:
        recomputed = analyze_external_evidence_agreement(nli_report=nli_report)
    except (EvidenceAgreementError, TypeError, AttributeError, ValueError) as exc:
        raise CorroborationDecisionError("invalid_upstream_evidence") from exc
    if agreement_report != recomputed:
        raise CorroborationDecisionError("agreement_and_nli_reports_mismatch")
    if independence_review is not None:
        if not isinstance(independence_review, ExternalIndependenceReview):
            raise CorroborationDecisionError("invalid_independence_review")
        try:
            expected_review = build_external_independence_review(
                nli_report=nli_report, agreement_report=recomputed,
            )
        except ExternalIndependenceReviewError as exc:
            raise CorroborationDecisionError("invalid_independence_review") from exc
        if independence_review != expected_review:
            raise CorroborationDecisionError("independence_review_mismatch")

    origin_summary = None
    if reporting_origin_audit is not None:
        if independence_review is None:
            raise CorroborationDecisionError("origin_audit_requires_independence_review")
        try:
            origin_summary = summarize_reporting_origin_audit(
                nli_report=nli_report, agreement_report=recomputed,
                independence_review=independence_review, audit=reporting_origin_audit,
            )
        except (ReportingOriginAuditError, TypeError, AttributeError, ValueError) as exc:
            raise CorroborationDecisionError("invalid_reporting_origin_audit") from exc

    # Evaluate actual passage stances, not raw publisher or article counts.
    has_support = bool(recomputed.supporting_unit_count or recomputed.mixed_unit_count)
    has_refute = bool(recomputed.refuting_unit_count or recomputed.mixed_unit_count)
    codes: set[str] = set()
    if has_support and has_refute:
        verdict = ExternalEvidenceVerdict.CONFLICTING_EVIDENCE
        codes.add("OPPOSING_DECISIVE_NLI_EVIDENCE")
    elif has_support:
        verdict = ExternalEvidenceVerdict.PROVISIONAL_SUPPORT
        codes.add("DECISIVE_SUPPORTING_NLI_ONLY")
    elif has_refute:
        verdict = ExternalEvidenceVerdict.PROVISIONAL_REFUTATION
        codes.add("DECISIVE_REFUTING_NLI_ONLY")
    else:
        verdict = ExternalEvidenceVerdict.INSUFFICIENT_EVIDENCE
        codes.add("NO_DECISIVE_NLI_EVIDENCE")

    if recomputed.provisional_agreement_unit_count == 1:
        codes.add("SINGLE_DEPENDENCY_RISK_UNIT")
    if recomputed.provisional_agreement_unit_count < recomputed.raw_dependency_risk_family_count:
        codes.add("DUPLICATE_EVIDENCE_LINKS_SOURCE_RISK_FAMILIES")
    if recomputed.mixed_unit_count:
        codes.add("WITHIN_RISK_UNIT_NLI_CONFLICT")
    if recomputed.inconclusive_passages:
        codes.add("SOME_EVIDENCE_NOT_DECISIVE")
    codes.add("SOURCE_EDITORIAL_INDEPENDENCE_NOT_PROVEN")
    if independence_review is not None and independence_review.review_candidates:
        codes.add("ORIGIN_REVIEW_CANDIDATES_REQUIRE_INDEPENDENT_AUDIT")
    audit_warnings: set[str] = set()
    if origin_summary is not None and reporting_origin_audit is not None:
        codes.add("REPORTING_ORIGIN_AUDIT_NOT_AUTHENTICATED_PROOF")
        audit_warnings.update(reporting_origin_audit.warnings)
        if origin_summary.dependency_indicated_pair_count:
            codes.add("REPORTING_ORIGIN_DEPENDENCY_INDICATED")
            audit_warnings.add("REPORTING_ORIGIN_DEPENDENCY_INDICATED")
        if origin_summary.unverified_origin_pair_count:
            audit_warnings.add("REPORTING_ORIGIN_CLAIMS_UNVERIFIED")
        if origin_summary.unreviewed_pair_count:
            audit_warnings.add("REPORTING_ORIGIN_PAIRS_NOT_REVIEWED")
    codes.add("NO_INDEPENDENT_CORROBORATION_CLAIM")
    codes.add("NLI_SCORES_NOT_TRUTH_PROBABILITIES")
    if recomputed.subject_excluded_decisive_passage_ids:
        codes.add("SUBJECT_UNGROUNDED_DECISIVE_NLI_EXCLUDED")
    if recomputed.scope_excluded_decisive_passages:
        codes.add("SCOPE_UNRESOLVED_DECISIVE_NLI_EXCLUDED")
        codes.update(code for _, reasons in recomputed.scope_excluded_decisive_passages for code in reasons)

    rows = recomputed.evidence
    # Use freshly rebuilt, subject-admitted votes, not raw threshold flags.
    support_ids = tuple(sorted((pid for unit in recomputed.units for pid in unit.support_passage_ids), key=lambda x: x.hex))
    refute_ids = tuple(sorted((pid for unit in recomputed.units for pid in unit.refute_passage_ids), key=lambda x: x.hex))
    inconclusive_ids = tuple(sorted((pid for unit in recomputed.units for pid in unit.inconclusive_passage_ids), key=lambda x: x.hex))
    return ExternalCorroborationDecision(
        claim=recomputed.claim,
        assessed_at=recomputed.assessed_at,
        evidence_verdict=verdict,
        evidence_passage_ids=tuple(sorted((x.passage_id for x in rows), key=lambda x: x.hex)),
        supporting_passage_ids=support_ids,
        refuting_passage_ids=refute_ids,
        inconclusive_passage_ids=inconclusive_ids,
        provisional_unit_count=recomputed.provisional_agreement_unit_count,
        supporting_unit_count=recomputed.supporting_unit_count,
        refuting_unit_count=recomputed.refuting_unit_count,
        mixed_unit_count=recomputed.mixed_unit_count,
        inconclusive_unit_count=recomputed.inconclusive_unit_count,
        source_risk_family_count=recomputed.raw_dependency_risk_family_count,
        explanation_codes=tuple(sorted(codes)),
        origin_review_pair_count=(
            len(independence_review.review_candidates) if independence_review is not None else 0
        ),
        origin_review_packet_sha256=(
            independence_review.review_packet_sha256 if independence_review is not None else None
        ),
        origin_audit=origin_summary,
        subject_excluded_decisive_passage_ids=recomputed.subject_excluded_decisive_passage_ids,
        decisive_admissibility_policy_version=recomputed.decisive_admissibility_policy_version,
        scope_excluded_decisive_passages=recomputed.scope_excluded_decisive_passages,
        policy_version=(
            ORIGIN_AUDIT_DECISION_POLICY_VERSION if origin_summary is not None
            else DECISION_POLICY_VERSION
        ),
        warnings=tuple(sorted(set(recomputed.warnings) | audit_warnings | {
            "THESE_ARE_PROVISIONAL_TEXTUAL_EVIDENCE_STANCES_NOT_FACT_CHECKS",
            "SOURCE_INDEPENDENCE_NOT_ESTABLISHED_BY_DIFFERENT_DOMAINS_OR_RISK_FAMILIES",
            "NO_INDEPENDENT_CORROBORATION_WITHOUT_SEPARATE_AUDITED_PROOF",
        })),
    )

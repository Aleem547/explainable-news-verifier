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

DECISION_POLICY_VERSION = "phase13d7-conservative-v1"


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


def decide_external_corroboration(
    *,
    nli_report: ExternalNliReport,
    agreement_report: ExternalAgreementReport,
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
    codes.add("NO_INDEPENDENT_CORROBORATION_CLAIM")
    codes.add("NLI_SCORES_NOT_TRUTH_PROBABILITIES")

    rows = recomputed.evidence
    support_ids = tuple(sorted((x.passage_id for x in rows if x.nli_threshold_passed and x.nli_label == "ENTAILMENT"), key=lambda x: x.hex))
    refute_ids = tuple(sorted((x.passage_id for x in rows if x.nli_threshold_passed and x.nli_label == "CONTRADICTION"), key=lambda x: x.hex))
    inconclusive_ids = tuple(sorted((x.passage_id for x in rows if not x.nli_threshold_passed), key=lambda x: x.hex))
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
        warnings=tuple(sorted(set(recomputed.warnings) | {
            "THESE_ARE_PROVISIONAL_TEXTUAL_EVIDENCE_STANCES_NOT_FACT_CHECKS",
            "SOURCE_INDEPENDENCE_NOT_ESTABLISHED_BY_DIFFERENT_DOMAINS_OR_RISK_FAMILIES",
            "NO_INDEPENDENT_CORROBORATION_WITHOUT_SEPARATE_AUDITED_PROOF",
        })),
    )

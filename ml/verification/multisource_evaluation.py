"""Phase 9G invariants, not accuracy measurements on unseen factual labels."""

from dataclasses import dataclass
from uuid import UUID

from ml.verification.cross_source import (
    CorroborationAssessment,
    CorroborationOutcome,
    EvidenceDecision,
)


@dataclass(frozen=True)
class ReliabilitySummary:
    evidence_count: int
    decisive_count: int
    blocked_count: int
    supporting_family_count: int
    refuting_family_count: int
    independence_claimed: bool
    has_opposing_evidence: bool


def summarize_reliability(result: CorroborationAssessment) -> ReliabilitySummary:
    """Check that an outcome reflects the audited findings and never proves independence."""
    support: set[UUID] = set()
    refute: set[UUID] = set()
    for row in result.findings:
        if row.decision == EvidenceDecision.ELIGIBLE:
            if row.stance == "ENTAILMENT":
                support.add(row.family_id)
            elif row.stance == "CONTRADICTION":
                refute.add(row.family_id)
    if support != set(result.supporting_family_ids) or refute != set(result.refuting_family_ids):
        raise ValueError("Corroboration family counts disagree with passage-level audit")
    has_opposing = bool(support and refute)
    if has_opposing != (result.outcome == CorroborationOutcome.UNRESOLVED_OPPOSING_EVIDENCE):
        raise ValueError("Opposing evidence was lost in the reported outcome")
    if result.independence_status != "NOT_ESTABLISHED":
        raise ValueError("Provisional evidence families cannot establish independence")
    return ReliabilitySummary(
        evidence_count=len(result.findings),
        decisive_count=result.decisive_count,
        blocked_count=sum(
            row.decision == EvidenceDecision.ADMISSIBILITY_BLOCKED for row in result.findings
        ),
        supporting_family_count=len(support),
        refuting_family_count=len(refute),
        independence_claimed=False,
        has_opposing_evidence=has_opposing,
    )

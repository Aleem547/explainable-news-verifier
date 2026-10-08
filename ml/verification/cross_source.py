"""Auditable cross-source evidence signals without false independence claims.

Only complete, immutable document passages may enter the persistence layer.
Different Phase 9E families are NOT certified independent reporting sources.
NLI is supplied by the caller; this module does not run or calibrate models.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from ml.verification.source_context import FreshnessStatus, TemporalRelation

RULE_VERSION = "phase9f-v1"


class EvidenceStance(StrEnum):
    ENTAILMENT = "ENTAILMENT"
    CONTRADICTION = "CONTRADICTION"
    NEUTRAL = "NEUTRAL"


class CorroborationOutcome(StrEnum):
    NO_DECISIVE_EVIDENCE = "NO_DECISIVE_EVIDENCE"
    SINGLE_FAMILY_SUPPORT = "SINGLE_FAMILY_SUPPORT"
    SINGLE_FAMILY_REFUTATION = "SINGLE_FAMILY_REFUTATION"
    MULTI_FAMILY_SUPPORT_UNVERIFIED = "MULTI_FAMILY_SUPPORT_UNVERIFIED"
    MULTI_FAMILY_REFUTATION_UNVERIFIED = "MULTI_FAMILY_REFUTATION_UNVERIFIED"
    UNRESOLVED_OPPOSING_EVIDENCE = "UNRESOLVED_OPPOSING_EVIDENCE"


class EvidenceDecision(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    NEUTRAL = "NEUTRAL"
    BELOW_CONFIDENCE_THRESHOLD = "BELOW_CONFIDENCE_THRESHOLD"
    NLI_NOT_ACCEPTED = "NLI_NOT_ACCEPTED"
    ADMISSIBILITY_BLOCKED = "ADMISSIBILITY_BLOCKED"
    TEMPORAL_REVIEW_REQUIRED = "TEMPORAL_REVIEW_REQUIRED"


@dataclass(frozen=True, slots=True)
class EvidenceInput:
    version_id: UUID
    passage_id: UUID
    stance: EvidenceStance
    confidence: float
    nli_accepted: bool
    admissible: bool
    temporal_relation: TemporalRelation | None = None
    freshness_status: FreshnessStatus | None = None


@dataclass(frozen=True, slots=True)
class EvidenceFinding:
    version_id: UUID
    passage_id: UUID
    family_id: UUID
    stance: EvidenceStance
    confidence: float
    decision: EvidenceDecision

    @property
    def decisive(self) -> bool:
        return self.decision == EvidenceDecision.ELIGIBLE


@dataclass(frozen=True, slots=True)
class CorroborationAssessment:
    outcome: CorroborationOutcome
    findings: tuple[EvidenceFinding, ...]
    supporting_family_ids: tuple[UUID, ...]
    refuting_family_ids: tuple[UUID, ...]
    mixed_family_ids: tuple[UUID, ...]
    warnings: tuple[str, ...]
    independence_status: str = "NOT_ESTABLISHED"
    rule_version: str = RULE_VERSION

    @property
    def decisive_count(self) -> int:
        return sum(finding.decisive for finding in self.findings)


def assess_cross_source(
    *,
    families: tuple[tuple[UUID, ...], ...],
    evidence: tuple[EvidenceInput, ...],
    possible_reuse_pairs: frozenset[frozenset[UUID]] = frozenset(),
    confidence_threshold: float = 0.90,
) -> CorroborationAssessment:
    """Count one provisional family per stance, never one vote per article.

    Contradictory findings are preserved (including inside one family). A
    different family is an *unresolved independence question*, not proof of
    external corroboration. Temporal flags trigger review, not refutation.
    """
    if not math.isfinite(confidence_threshold) or not 0.0 < confidence_threshold <= 1.0:
        raise ValueError("Confidence threshold must be finite and in (0, 1]")
    if not families or len(families) > 50:
        raise ValueError("Expected between 1 and 50 provisional families")
    if not 1 <= len(evidence) <= 100:
        raise ValueError("Expected between 1 and 100 evidence passages")
    all_ids = [version for family in families for version in family]
    if any(not family for family in families) or len(set(all_ids)) != len(all_ids):
        raise ValueError("Families must be nonempty and disjoint")
    if len({item.passage_id for item in evidence}) != len(evidence):
        raise ValueError("Evidence passage IDs must be unique")
    version_families = {
        version_id: min(family, key=lambda key: key.hex)
        for family in families
        for version_id in family
    }
    if any(item.version_id not in version_families for item in evidence):
        raise ValueError("Evidence version missing from independence assessment")
    if any(len(pair) != 2 or not pair <= set(all_ids) for pair in possible_reuse_pairs):
        raise ValueError("Possible-reuse pairs must refer to two assessed versions")

    findings: list[EvidenceFinding] = []
    support: set[UUID] = set()
    refute: set[UUID] = set()
    warnings = ["INDEPENDENT_REPORTING_NOT_ESTABLISHED", "NOT_A_CLAIM_TRUTH_PROBABILITY"]
    for item in evidence:
        if not isinstance(item.stance, EvidenceStance):
            raise ValueError("Use a declared EvidenceStance")
        if not math.isfinite(item.confidence) or not 0.0 <= item.confidence <= 1.0:
            raise ValueError("Evidence confidence must be finite and in [0, 1]")
        if item.stance == EvidenceStance.NEUTRAL:
            decision = EvidenceDecision.NEUTRAL
        elif not item.nli_accepted:
            decision = EvidenceDecision.NLI_NOT_ACCEPTED
        elif not item.admissible:
            decision = EvidenceDecision.ADMISSIBILITY_BLOCKED
        elif item.confidence < confidence_threshold:
            decision = EvidenceDecision.BELOW_CONFIDENCE_THRESHOLD
        elif item.freshness_status in {
            FreshnessStatus.OLDER_THAN_WINDOW,
            FreshnessStatus.FUTURE_DATED,
        }:
            decision = EvidenceDecision.TEMPORAL_REVIEW_REQUIRED
        else:
            decision = EvidenceDecision.ELIGIBLE
        if item.temporal_relation == TemporalRelation.AFTER_REFERENCE:
            warnings.append("EVIDENCE_PUBLISHED_AFTER_REFERENCE_REVIEW_CONTEXT")
        if item.temporal_relation is None or item.freshness_status is None:
            warnings.append("SOME_EVIDENCE_LACKS_AUDITED_TEMPORAL_CONTEXT")
        family_id = version_families[item.version_id]
        findings.append(
            EvidenceFinding(
                version_id=item.version_id,
                passage_id=item.passage_id,
                family_id=family_id,
                stance=item.stance,
                confidence=item.confidence,
                decision=decision,
            )
        )
        if decision == EvidenceDecision.TEMPORAL_REVIEW_REQUIRED:
            warnings.append("TEMPORAL_REVIEW_REQUIRED")
        if decision == EvidenceDecision.ELIGIBLE:
            if item.stance == EvidenceStance.ENTAILMENT:
                support.add(family_id)
            else:
                refute.add(family_id)

    mixed = support & refute
    if mixed or (support and refute):
        outcome = CorroborationOutcome.UNRESOLVED_OPPOSING_EVIDENCE
        warnings.append("OPPOSING_EVIDENCE_NEEDS_REVIEW")
    elif len(support) > 1:
        outcome = CorroborationOutcome.MULTI_FAMILY_SUPPORT_UNVERIFIED
    elif len(refute) > 1:
        outcome = CorroborationOutcome.MULTI_FAMILY_REFUTATION_UNVERIFIED
    elif support:
        outcome = CorroborationOutcome.SINGLE_FAMILY_SUPPORT
    elif refute:
        outcome = CorroborationOutcome.SINGLE_FAMILY_REFUTATION
    else:
        outcome = CorroborationOutcome.NO_DECISIVE_EVIDENCE
    decisive_versions = {finding.version_id for finding in findings if finding.decisive}
    if any(pair <= decisive_versions for pair in possible_reuse_pairs):
        warnings.append("POSSIBLE_SHARED_ORIGIN_BETWEEN_DECISIVE_FAMILIES")
    if mixed:
        warnings.append("OPPOSING_EVIDENCE_WITHIN_SAME_FAMILY")
    return CorroborationAssessment(
        outcome=outcome,
        findings=tuple(findings),
        supporting_family_ids=tuple(sorted(support, key=lambda key: key.hex)),
        refuting_family_ids=tuple(sorted(refute, key=lambda key: key.hex)),
        mixed_family_ids=tuple(sorted(mixed, key=lambda key: key.hex)),
        warnings=tuple(dict.fromkeys(warnings)),
    )

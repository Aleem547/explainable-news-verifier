"""Auditable, page-grouped aggregation of accepted sentence-level NLI decisions.

One Wikipedia page is a *group*, not an independent external source. Neither
confidence summation nor voting across its sentences is justified here.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class AggregationReason(StrEnum):
    NO_DECISIVE_EVIDENCE = "NO_DECISIVE_EVIDENCE"
    SUPPORT_ONLY = "SUPPORT_ONLY"
    REFUTATION_ONLY = "REFUTATION_ONLY"
    OPPOSING_EVIDENCE = "OPPOSING_EVIDENCE"


class ContributionRole(StrEnum):
    PRIMARY_SUPPORT = "PRIMARY_SUPPORT"
    PRIMARY_REFUTATION = "PRIMARY_REFUTATION"
    SAME_PAGE_ADDITIONAL = "SAME_PAGE_ADDITIONAL"
    NOT_DECISIVE = "NOT_DECISIVE"


class EvidenceForAggregation(Protocol):
    @property
    def rank(self) -> int: ...

    @property
    def page_id(self) -> str: ...

    @property
    def sentence_id(self) -> int: ...

    @property
    def nli_label(self) -> str: ...

    @property
    def nli_confidence(self) -> float: ...

    @property
    def accepted(self) -> bool: ...


@dataclass(frozen=True)
class AggregationResult:
    verdict: str
    reason: AggregationReason
    supporting_pages: list[str]
    refuting_pages: list[str]
    supporting_evidence_count: int
    refuting_evidence_count: int
    primary_keys: frozenset[tuple[int, str, int]]

    @property
    def primary_count(self) -> int:
        return len(self.primary_keys)


def _item_key(item: EvidenceForAggregation) -> tuple[int, str, int]:
    return (item.rank, item.page_id, item.sentence_id)


def aggregate_evidence(items: Sequence[EvidenceForAggregation]) -> AggregationResult:
    """Select strongest accepted sentence per (page, stance), without averaging.

    Multiple accepted sentences from the same article do not create additional
    page votes. Contradictions within an article are preserved, not cancelled.
    The returned verdict is provisional and does NOT claim source independence.
    """
    best: dict[tuple[str, str], EvidenceForAggregation] = {}
    counts = {"ENTAILMENT": 0, "CONTRADICTION": 0}

    for item in items:
        if not item.accepted or item.nli_label not in counts:
            continue
        counts[item.nli_label] += 1
        group = (item.page_id, item.nli_label)
        previous = best.get(group)
        if previous is None or (item.nli_confidence, -item.rank, -item.sentence_id) > (
            previous.nli_confidence,
            -previous.rank,
            -previous.sentence_id,
        ):
            best[group] = item

    support = sorted(page for page, label in best if label == "ENTAILMENT")
    refute = sorted(page for page, label in best if label == "CONTRADICTION")

    if support and refute:
        verdict = "CONFLICTING_EVIDENCE"
        reason = AggregationReason.OPPOSING_EVIDENCE
    elif support:
        verdict = "SUPPORTING_EVIDENCE"
        reason = AggregationReason.SUPPORT_ONLY
    elif refute:
        verdict = "REFUTING_EVIDENCE"
        reason = AggregationReason.REFUTATION_ONLY
    else:
        verdict = "INSUFFICIENT_EVIDENCE"
        reason = AggregationReason.NO_DECISIVE_EVIDENCE

    return AggregationResult(
        verdict=verdict,
        reason=reason,
        supporting_pages=support,
        refuting_pages=refute,
        supporting_evidence_count=counts["ENTAILMENT"],
        refuting_evidence_count=counts["CONTRADICTION"],
        primary_keys=frozenset(_item_key(item) for item in best.values()),
    )


def contribution_role(item: EvidenceForAggregation, summary: AggregationResult) -> ContributionRole:
    """Make every candidate's role in the page-grouped verdict explicit."""
    if not item.accepted or item.nli_label not in ("ENTAILMENT", "CONTRADICTION"):
        return ContributionRole.NOT_DECISIVE
    if _item_key(item) in summary.primary_keys:
        if item.nli_label == "ENTAILMENT":
            return ContributionRole.PRIMARY_SUPPORT
        return ContributionRole.PRIMARY_REFUTATION
    return ContributionRole.SAME_PAGE_ADDITIONAL

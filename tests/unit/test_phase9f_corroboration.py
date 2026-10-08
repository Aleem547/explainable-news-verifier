"""Offline correctness tests for the Phase 9F conservative aggregator."""

from dataclasses import replace
from uuid import UUID

import pytest

from ml.verification.cross_source import (
    CorroborationOutcome,
    EvidenceDecision,
    EvidenceInput,
    EvidenceStance,
    assess_cross_source,
)
from ml.verification.source_context import FreshnessStatus, TemporalRelation

A, B, C, D = (UUID(int=i) for i in range(1, 5))


def evidence(version: UUID, passage: int, **overrides: object) -> EvidenceInput:
    base = EvidenceInput(
        version_id=version,
        passage_id=UUID(int=passage),
        stance=EvidenceStance.ENTAILMENT,
        confidence=0.96,
        nli_accepted=True,
        admissible=True,
    )
    return replace(base, **overrides)


def run(
    families: tuple[tuple[UUID, ...], ...],
    *items: EvidenceInput,
    reuse: frozenset[frozenset[UUID]] = frozenset(),
):
    return assess_cross_source(families=families, evidence=items, possible_reuse_pairs=reuse)


def test_identical_article_versions_one_family_not_two_votes() -> None:
    result = run(((A, B),), evidence(A, 11), evidence(B, 12))
    assert result.outcome == CorroborationOutcome.SINGLE_FAMILY_SUPPORT
    assert len(result.supporting_family_ids) == 1
    assert result.decisive_count == 2
    assert result.independence_status == "NOT_ESTABLISHED"


def test_different_provisional_families_are_not_called_independent() -> None:
    result = run(((A,), (B,)), evidence(A, 11), evidence(B, 12))
    assert result.outcome == CorroborationOutcome.MULTI_FAMILY_SUPPORT_UNVERIFIED
    assert "INDEPENDENT_REPORTING_NOT_ESTABLISHED" in result.warnings


def test_neutral_and_abstained_do_not_count() -> None:
    result = run(
        ((A,), (B,)),
        evidence(A, 11, stance=EvidenceStance.NEUTRAL),
        evidence(B, 12, nli_accepted=False),
    )
    assert result.outcome == CorroborationOutcome.NO_DECISIVE_EVIDENCE
    assert [f.decision for f in result.findings] == [
        EvidenceDecision.NEUTRAL,
        EvidenceDecision.NLI_NOT_ACCEPTED,
    ]


def test_opposing_families_do_not_cancel_into_support() -> None:
    result = run(
        ((A,), (B,)), evidence(A, 11), evidence(B, 12, stance=EvidenceStance.CONTRADICTION)
    )
    assert result.outcome == CorroborationOutcome.UNRESOLVED_OPPOSING_EVIDENCE
    assert len(result.supporting_family_ids) == len(result.refuting_family_ids) == 1


def test_opposing_inside_same_family_is_visible() -> None:
    result = run(((A, B),), evidence(A, 11), evidence(B, 12, stance=EvidenceStance.CONTRADICTION))
    assert result.mixed_family_ids == (A,)
    assert "OPPOSING_EVIDENCE_WITHIN_SAME_FAMILY" in result.warnings


def test_refutation_from_multiple_families_unverified() -> None:
    result = run(
        ((A,), (B,)),
        evidence(A, 11, stance=EvidenceStance.CONTRADICTION),
        evidence(B, 12, stance=EvidenceStance.CONTRADICTION),
    )
    assert result.outcome == CorroborationOutcome.MULTI_FAMILY_REFUTATION_UNVERIFIED


@pytest.mark.parametrize("confidence", [0.2, 0.8999])
def test_below_threshold_not_decisive(confidence: float) -> None:
    result = run(((A,),), evidence(A, 11, confidence=confidence))
    assert result.findings[0].decision == EvidenceDecision.BELOW_CONFIDENCE_THRESHOLD


def test_unadmissible_nli_must_not_count() -> None:
    result = run(((A,),), evidence(A, 11, admissible=False))
    assert result.findings[0].decision == EvidenceDecision.ADMISSIBILITY_BLOCKED


@pytest.mark.parametrize(
    "status",
    [FreshnessStatus.FUTURE_DATED, FreshnessStatus.OLDER_THAN_WINDOW],
)
def test_temporal_review_blocks_automatic_decision(status: FreshnessStatus) -> None:
    result = run(((A,),), evidence(A, 11, freshness_status=status))
    assert result.findings[0].decision == EvidenceDecision.TEMPORAL_REVIEW_REQUIRED
    assert "TEMPORAL_REVIEW_REQUIRED" in result.warnings


def test_after_reference_warns_but_not_automatically_refutes() -> None:
    result = run(((A,),), evidence(A, 11, temporal_relation=TemporalRelation.AFTER_REFERENCE))
    assert result.outcome == CorroborationOutcome.SINGLE_FAMILY_SUPPORT
    assert "EVIDENCE_PUBLISHED_AFTER_REFERENCE_REVIEW_CONTEXT" in result.warnings


def test_possible_shared_origin_flagged_without_automatic_merging() -> None:
    result = run(
        ((A,), (B,)),
        evidence(A, 11),
        evidence(B, 12),
        reuse=frozenset((frozenset((A, B)),)),
    )
    assert "POSSIBLE_SHARED_ORIGIN_BETWEEN_DECISIVE_FAMILIES" in result.warnings
    assert result.outcome == CorroborationOutcome.MULTI_FAMILY_SUPPORT_UNVERIFIED


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, 1.01])
def test_reject_invalid_confidence(bad: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        run(((A,),), evidence(A, 11, confidence=bad))


def test_reject_duplicate_passage_ids() -> None:
    with pytest.raises(ValueError, match="passage IDs"):
        run(((A,),), evidence(A, 11), evidence(A, 11))


def test_reject_overlapping_families() -> None:
    with pytest.raises(ValueError, match="disjoint"):
        run(((A, B), (B, C)), evidence(A, 11))


def test_reject_version_not_assessed() -> None:
    with pytest.raises(ValueError, match="missing"):
        run(((A,),), evidence(C, 11))


def test_reject_invalid_pair_membership() -> None:
    with pytest.raises(ValueError, match="Possible-reuse"):
        run(((A,), (B,)), evidence(A, 11), reuse=frozenset((frozenset((A, D)),)))


def test_no_truth_probability_field() -> None:
    result = run(((A,),), evidence(A, 11))
    assert not hasattr(result, "truth_probability")
    assert result.independence_status == "NOT_ESTABLISHED"

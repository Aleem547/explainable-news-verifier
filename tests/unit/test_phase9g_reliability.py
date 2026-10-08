"""No false vote multiplication, hidden conflicts, or independence claims."""

from uuid import UUID

from ml.verification.cross_source import EvidenceInput, EvidenceStance, assess_cross_source
from ml.verification.multisource_evaluation import summarize_reliability

A, B, C = (UUID(int=i) for i in (1, 2, 3))


def row(version: UUID, pid: int, stance: EvidenceStance, admissible: bool = True) -> EvidenceInput:
    return EvidenceInput(version, UUID(int=pid), stance, 0.96, True, admissible)


def test_reused_reports_count_once() -> None:
    assessment = assess_cross_source(
        families=((A, B), (C,)),
        evidence=(row(A, 11, EvidenceStance.ENTAILMENT), row(B, 12, EvidenceStance.ENTAILMENT)),
    )
    summary = summarize_reliability(assessment)
    assert summary.supporting_family_count == 1
    assert not summary.independence_claimed


def test_opposing_evidence_preserved() -> None:
    assessment = assess_cross_source(
        families=((A,), (B,)),
        evidence=(row(A, 11, EvidenceStance.ENTAILMENT), row(B, 12, EvidenceStance.CONTRADICTION)),
    )
    summary = summarize_reliability(assessment)
    assert summary.has_opposing_evidence
    assert summary.refuting_family_count == 1


def test_unadmitted_passage_is_not_a_vote() -> None:
    assessment = assess_cross_source(
        families=((A,), (B,)),
        evidence=(row(A, 11, EvidenceStance.ENTAILMENT, False),),
    )
    summary = summarize_reliability(assessment)
    assert summary.blocked_count == 1
    assert summary.decisive_count == 0

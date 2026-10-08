"""Phase 9G pure-function diagnostic; no network, database or transformer load."""

from uuid import UUID

from ml.verification.cross_source import EvidenceInput, EvidenceStance, assess_cross_source
from ml.verification.external_admissibility import external_subject_grounded
from ml.verification.multisource_evaluation import summarize_reliability


def main() -> None:
    versions = (UUID(int=1), UUID(int=2), UUID(int=3))
    examples = (
        EvidenceInput(versions[0], UUID(int=11), EvidenceStance.ENTAILMENT, 0.98, True, True),
        EvidenceInput(versions[1], UUID(int=12), EvidenceStance.ENTAILMENT, 0.96, True, True),
        EvidenceInput(versions[2], UUID(int=13), EvidenceStance.CONTRADICTION, 0.94, True, True),
    )
    result = assess_cross_source(
        families=((versions[0], versions[1]), (versions[2],)), evidence=examples
    )
    summary = summarize_reliability(result)
    assert result.outcome == "UNRESOLVED_OPPOSING_EVIDENCE"
    assert summary.supporting_family_count == 1
    assert summary.refuting_family_count == 1
    assert not summary.independence_claimed
    assert external_subject_grounded(
        "The Eiffel Tower is in Paris", "The Eiffel Tower stands in Paris."
    )
    assert not external_subject_grounded(
        "The Eiffel Tower is in Paris", "An unrelated building stands elsewhere."
    )
    print("Phase 9G offline reliability checks passed")
    print("Three passages, two families, preserved opposing evidence")
    print("Independence NOT established; no network, database or model load")


if __name__ == "__main__":
    main()

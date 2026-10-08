"""Offline Phase 9F diagnostic; no external calls, model loads or database writes."""

from uuid import UUID

from ml.verification.cross_source import (
    CorroborationOutcome,
    EvidenceInput,
    EvidenceStance,
    assess_cross_source,
)


def main() -> None:
    first, copy, second = (UUID(int=i) for i in (1, 2, 3))
    rows = tuple(
        EvidenceInput(
            version_id=version,
            passage_id=UUID(int=i + 10),
            stance=EvidenceStance.ENTAILMENT,
            confidence=0.96,
            nli_accepted=True,
            admissible=True,
        )
        for i, version in enumerate((first, copy, second))
    )
    result = assess_cross_source(families=((first, copy), (second,)), evidence=rows)
    assert result.outcome == CorroborationOutcome.MULTI_FAMILY_SUPPORT_UNVERIFIED
    assert len(result.supporting_family_ids) == 2
    assert result.independence_status == "NOT_ESTABLISHED"
    print("Phase 9F offline corroboration checks passed")
    print(
        f"Passages: {len(rows)}; "
        f"provisional supporting families: {len(result.supporting_family_ids)}"
    )
    print(f"Outcome: {result.outcome.value}")
    print("Independence is NOT established; no claim verdict or network/database operation")


if __name__ == "__main__":
    main()

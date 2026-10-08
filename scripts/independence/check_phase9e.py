"""Offline, repeatable Phase 9E smoke test; performs no database writes."""

from uuid import UUID

from ml.verification.source_independence import Relationship, Snapshot, assess_source_independence


def main() -> None:
    shared = (
        "An authorized syndicated report cites the original agency and gives detailed "
        "information about the same event in the same reporting order. " * 3
    )
    left = Snapshot(UUID(int=1), UUID(int=11), shared)
    right = Snapshot(UUID(int=2), UUID(int=12), shared)
    independent_unknown = Snapshot(
        UUID(int=3),
        UUID(int=13),
        "Different organizations publish their own statements and investigations, "
        "but this metadata alone cannot prove original independent reporting.",
    )
    result = assess_source_independence([left, right, independent_unknown])
    assert result.family_count == 2
    assert any(pair.relationship == Relationship.IDENTICAL_TEXT for pair in result.pairs)
    assert "INDEPENDENCE_NOT_PROVEN" in result.warnings
    print("Phase 9E offline evidence-family checks passed")
    print(f"Snapshots: {len(result.version_ids)}")
    print(f"Provisional evidence families: {result.family_count}")
    print("No network calls, database writes, or claim verdicts performed")


if __name__ == "__main__":
    main()

"""Phase 8D scoring tests. These run without loading ML models."""

import pytest

from ml.verification.benchmark import (
    BenchmarkCase,
    BenchmarkExample,
    EvidenceKey,
    EvidenceObservation,
    build_failure_rows,
    evidence_hit,
    select_balanced_examples,
    summarize_benchmark,
)


def example(
    claim_id: int,
    label: str,
    gold_sets: tuple[frozenset[EvidenceKey], ...] = (),
) -> BenchmarkExample:
    return BenchmarkExample(claim_id, "test", label, f"Claim {claim_id}", gold_sets)


def case(
    claim_id: int,
    label: str,
    verdict: str,
    gold_sets: tuple[frozenset[EvidenceKey], ...] = (),
    observed: tuple[EvidenceObservation, ...] = (),
) -> BenchmarkCase:
    return BenchmarkCase(
        example=example(claim_id, label, gold_sets),
        verdict=verdict,
        latency_ms=100.0,
        retrieved_count=10,
        assessed_count=len(observed),
        excluded_count=2,
        aggregation_reason="TEST",
        evidence=observed,
        exclusions=("DISAMBIGUATION_PAGE", "ENTITY_VARIANT_MISMATCH"),
    )


def observation(page: str, sentence: int) -> EvidenceObservation:
    return EvidenceObservation(
        page, sentence, "Some evidence", "ENTAILMENT", 0.95, True, "PRIMARY_SUPPORT"
    )


def test_balanced_sample_deterministic_and_unique() -> None:
    offsets = {"SUPPORTS": 1, "REFUTES": 100, "NOT ENOUGH INFO": 200}
    rows = [
        example(i, label)
        for label in ("SUPPORTS", "REFUTES", "NOT ENOUGH INFO")
        for i in range(offsets[label], offsets[label] + 20)
    ]
    first = select_balanced_examples(rows, max_examples=12, seed=42)
    second = select_balanced_examples(rows, max_examples=12, seed=42)
    assert first == second
    assert len(first) == 12
    assert [
        sum(row.label == label for row in first)
        for label in ("SUPPORTS", "REFUTES", "NOT ENOUGH INFO")
    ] == [4, 4, 4]
    assert len(set(row.claim_id for row in first)) == 12


def test_sample_fills_remainder_when_class_small() -> None:
    rows = [
        example(1, "SUPPORTS"),
        example(2, "REFUTES"),
        example(3, "REFUTES"),
        example(4, "NOT ENOUGH INFO"),
        example(5, "NOT ENOUGH INFO"),
    ]
    sample = select_balanced_examples(rows, max_examples=5, seed=4)
    assert len(sample) == 5


def test_sample_rejects_invalid_inputs() -> None:
    rows = [example(1, "SUPPORTS"), example(2, "REFUTES"), example(3, "NOT ENOUGH INFO")]
    with pytest.raises(ValueError, match="at least 3"):
        select_balanced_examples(rows, max_examples=2, seed=1)
    with pytest.raises(ValueError, match="Duplicate"):
        select_balanced_examples(rows + [rows[0]], max_examples=3, seed=1)
    with pytest.raises(ValueError, match="Each FEVER"):
        select_balanced_examples(rows[:2], max_examples=3, seed=1)


def test_verdict_mapping_and_conflict_are_explicit() -> None:
    assert case(1, "SUPPORTS", "SUPPORTING_EVIDENCE").mapped_label == "SUPPORTS"
    assert case(1, "REFUTES", "REFUTING_EVIDENCE").mapped_label == "REFUTES"
    assert case(1, "NOT ENOUGH INFO", "INSUFFICIENT_EVIDENCE").mapped_label == "NOT ENOUGH INFO"
    assert case(1, "SUPPORTS", "CONFLICTING_EVIDENCE").mapped_label == "CONFLICT"
    assert not case(1, "SUPPORTS", "CONFLICTING_EVIDENCE").decided
    with pytest.raises(ValueError, match="Unrecognized"):
        summarize_benchmark([case(1, "SUPPORTS", "MALFORMED")])


def test_summary_class_scores_and_selective_coverage() -> None:
    cases = [
        case(1, "SUPPORTS", "SUPPORTING_EVIDENCE"),
        case(2, "REFUTES", "REFUTING_EVIDENCE"),
        case(3, "NOT ENOUGH INFO", "INSUFFICIENT_EVIDENCE"),
        case(4, "SUPPORTS", "CONFLICTING_EVIDENCE"),
    ]
    m = summarize_benchmark(cases)
    assert m["total_cases"] == 4
    assert m["benchmark_label_agreement"] == 0.75
    assert m["decision_coverage"] == 0.5
    assert m["decided_accuracy"] == 1.0
    assert m["abstained_count"] == 2
    assert m["conflicting_count"] == 1
    assert m["confusion_matrix"]["SUPPORTS"]["CONFLICT"] == 1
    assert m["per_class"]["SUPPORTS"]["recall"] == 0.5
    assert m["gold_annotated_cases"] == 0
    assert m["assessed_complete_gold_set_rate"] is None
    assert m["exclusion_reasons"]["ENTITY_VARIANT_MISMATCH"] == 4


def test_all_abstentions_do_not_divide_by_zero() -> None:
    result = summarize_benchmark([case(1, "SUPPORTS", "INSUFFICIENT_EVIDENCE")])
    assert result["decided_accuracy"] is None
    assert result["decision_coverage"] == 0


def test_multi_sentence_gold_set_requires_all_sentences() -> None:
    refs = (frozenset({EvidenceKey("A", 1), EvidenceKey("A", 2)}),)
    partial = case(1, "SUPPORTS", "SUPPORTING_EVIDENCE", refs, (observation("A", 1),))
    full = case(
        2, "SUPPORTS", "SUPPORTING_EVIDENCE", refs, (observation("A", 1), observation("A", 2))
    )
    assert evidence_hit(partial) is not None
    assert evidence_hit(partial).any_sentence is True  # type: ignore[union-attr]
    assert evidence_hit(partial).complete_set is False  # type: ignore[union-attr]
    assert evidence_hit(full).complete_set is True  # type: ignore[union-attr]


def test_alternative_gold_sets_any_complete_is_hit() -> None:
    refs = (frozenset({EvidenceKey("A", 1), EvidenceKey("A", 2)}), frozenset({EvidenceKey("B", 3)}))
    item = case(1, "REFUTES", "REFUTING_EVIDENCE", refs, (observation("B", 3),))
    assert evidence_hit(item).complete_set is True  # type: ignore[union-attr]
    metrics = summarize_benchmark([item])
    assert metrics["gold_annotated_cases"] == 1
    assert metrics["assessed_complete_gold_set_rate"] == 1.0


def test_wrong_sentence_same_page_counts_page_hit_only() -> None:
    refs = (frozenset({EvidenceKey("Page_A", 1)}),)
    item = case(1, "SUPPORTS", "SUPPORTING_EVIDENCE", refs, (observation("Page_A", 9),))
    hit = evidence_hit(item)
    assert hit is not None
    assert hit.any_page is True
    assert hit.any_sentence is False
    assert hit.complete_set is False


def test_failures_include_incorrect_and_abstained_cases() -> None:
    examples = [
        case(1, "SUPPORTS", "REFUTING_EVIDENCE"),
        case(2, "SUPPORTS", "INSUFFICIENT_EVIDENCE"),
        case(3, "REFUTES", "CONFLICTING_EVIDENCE"),
        case(4, "NOT ENOUGH INFO", "INSUFFICIENT_EVIDENCE"),
    ]
    failures = build_failure_rows(examples)
    assert [row["failure_type"] for row in failures] == [
        "WRONG_DECISIVE_VERDICT",
        "ABSTENTION_ON_DECISIVE_GOLD",
        "CONFLICTING_PREDICTION",
    ]


def test_summary_rejects_duplicate_or_empty_cases() -> None:
    with pytest.raises(ValueError, match="No completed"):
        summarize_benchmark([])
    with pytest.raises(ValueError, match="Repeated"):
        summarize_benchmark([case(1, "SUPPORTS", "SUPPORTING_EVIDENCE")] * 2)

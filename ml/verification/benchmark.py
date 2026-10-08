"""Pure, auditable FEVER benchmark calculations for end-to-end verification.

A NOT ENOUGH INFO gold label is not the same as epistemic proof of absence.
The benchmark's three-way agreement is a proxy, not calibrated truth probability.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from random import Random

GOLD_LABELS = ("SUPPORTS", "REFUTES", "NOT ENOUGH INFO")
PREDICTED_LABELS = (*GOLD_LABELS, "CONFLICT")
VERDICT_MAPPING = {
    "SUPPORTING_EVIDENCE": "SUPPORTS",
    "REFUTING_EVIDENCE": "REFUTES",
    "INSUFFICIENT_EVIDENCE": "NOT ENOUGH INFO",
    "CONFLICTING_EVIDENCE": "CONFLICT",
}


@dataclass(frozen=True, order=True)
class EvidenceKey:
    page_id: str
    sentence_id: int


@dataclass(frozen=True)
class BenchmarkExample:
    claim_id: int
    split: str
    label: str
    claim: str
    gold_sets: tuple[frozenset[EvidenceKey], ...] = ()


@dataclass(frozen=True)
class EvidenceObservation:
    page_id: str
    sentence_id: int
    text: str
    nli_label: str
    nli_confidence: float
    accepted: bool
    contribution_role: str


@dataclass(frozen=True)
class BenchmarkCase:
    example: BenchmarkExample
    verdict: str
    latency_ms: float
    retrieved_count: int
    assessed_count: int
    excluded_count: int
    aggregation_reason: str
    evidence: tuple[EvidenceObservation, ...] = ()
    exclusions: tuple[str, ...] = ()

    @property
    def mapped_label(self) -> str:
        if self.verdict not in VERDICT_MAPPING:
            raise ValueError(f"Unrecognized pipeline verdict: {self.verdict!r}")
        return VERDICT_MAPPING[self.verdict]

    @property
    def decided(self) -> bool:
        return self.mapped_label in ("SUPPORTS", "REFUTES")


@dataclass(frozen=True)
class EvidenceHit:
    any_page: bool
    any_sentence: bool
    complete_set: bool


def select_balanced_examples(
    examples: Sequence[BenchmarkExample], *, max_examples: int, seed: int
) -> list[BenchmarkExample]:
    """Deterministic class-stratified sample without resampling or split mixing."""
    if max_examples < 3:
        raise ValueError("max_examples must be at least 3 for a three-class benchmark")
    ids = [(example.split, example.claim_id) for example in examples]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate (split, claim_id) in benchmark examples")
    groups: dict[str, list[BenchmarkExample]] = {label: [] for label in GOLD_LABELS}
    for example in examples:
        if example.label not in groups:
            raise ValueError(f"Unexpected FEVER gold label: {example.label!r}")
        if not example.claim.strip():
            raise ValueError("Cannot benchmark empty FEVER claims")
        groups[example.label].append(example)

    if any(not group for group in groups.values()):
        raise ValueError("Each FEVER gold class must be present before balanced sampling")

    rng = Random(seed)
    shuffled = {
        label: rng.sample(sorted(groups[label], key=lambda row: row.claim_id), len(groups[label]))
        for label in GOLD_LABELS
    }
    target = min(max_examples, len(examples))
    counts = {label: min(target // len(GOLD_LABELS), len(shuffled[label])) for label in GOLD_LABELS}
    allocated = sum(counts.values())
    while allocated < target:
        progressed = False
        for label in GOLD_LABELS:
            if allocated >= target:
                break
            if counts[label] < len(shuffled[label]):
                counts[label] += 1
                allocated += 1
                progressed = True
        if not progressed:
            break
    chosen = [example for label in GOLD_LABELS for example in shuffled[label][: counts[label]]]
    return sorted(chosen, key=lambda row: (row.label, row.claim_id))


def evidence_hit(case: BenchmarkCase) -> EvidenceHit | None:
    """Evaluate only *assessed* evidence against any complete gold evidence set.

    Retrieval candidates removed before NLI are not observable from Phase 8C's
    response and are intentionally excluded from this metric.
    """
    sets = case.example.gold_sets
    if not sets:
        return None
    observed = {EvidenceKey(item.page_id, item.sentence_id) for item in case.evidence}
    observed_pages = {key.page_id for key in observed}
    expected = set().union(*sets)
    return EvidenceHit(
        any_page=bool({key.page_id for key in expected} & observed_pages),
        any_sentence=bool(expected & observed),
        complete_set=any(gold_set.issubset(observed) for gold_set in sets),
    )


def _class_metrics(cases: Sequence[BenchmarkCase], label: str) -> dict[str, float | int]:
    tp = sum(1 for c in cases if c.example.label == label and c.mapped_label == label)
    fp = sum(1 for c in cases if c.example.label != label and c.mapped_label == label)
    fn = sum(1 for c in cases if c.example.label == label and c.mapped_label != label)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "support": tp + fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def summarize_benchmark(cases: Sequence[BenchmarkCase]) -> dict[str, object]:
    """Score every prediction. Conflicting outcomes count as non-matches.

    Decision coverage counts SUPPORTS/REFUTES only. Both INSUFFICIENT_EVIDENCE
    and CONFLICTING_EVIDENCE are treated as abstentions for selective metrics.
    """
    if not cases:
        raise ValueError("No completed benchmark cases")
    if len({(c.example.split, c.example.claim_id) for c in cases}) != len(cases):
        raise ValueError("Repeated benchmark claim in completed cases")
    for case in cases:
        if case.example.label not in GOLD_LABELS:
            raise ValueError(f"Unexpected gold label: {case.example.label}")
        _ = case.mapped_label

    total = len(cases)
    decided = [c for c in cases if c.decided]
    correct = sum(c.example.label == c.mapped_label for c in cases)
    selective_correct = sum(c.example.label == c.mapped_label for c in decided)
    per_class = {label: _class_metrics(cases, label) for label in GOLD_LABELS}
    hits = [h for case in cases if (h := evidence_hit(case)) is not None]
    exclusions = Counter(reason for case in cases for reason in case.exclusions)
    confusion = {label: {prediction: 0 for prediction in PREDICTED_LABELS} for label in GOLD_LABELS}
    for case in cases:
        confusion[case.example.label][case.mapped_label] += 1

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 6) if denominator else None

    return {
        "total_cases": total,
        "gold_label_distribution": dict(Counter(c.example.label for c in cases)),
        "predicted_label_distribution": dict(Counter(c.mapped_label for c in cases)),
        "benchmark_label_agreement": ratio(correct, total),
        "macro_f1": round(sum(float(m["f1"]) for m in per_class.values()) / 3, 6),
        "per_class": per_class,
        "confusion_matrix": confusion,
        "decision_coverage": ratio(len(decided), total),
        "decided_accuracy": ratio(selective_correct, len(decided)),
        "abstained_count": total - len(decided),
        "conflicting_count": sum(c.mapped_label == "CONFLICT" for c in cases),
        "mean_latency_ms": round(sum(c.latency_ms for c in cases) / total, 2),
        "mean_assessed_count": round(sum(c.assessed_count for c in cases) / total, 3),
        "exclusion_reasons": dict(sorted(exclusions.items())),
        "gold_annotated_cases": len(hits),
        "assessed_any_gold_page_rate": ratio(sum(h.any_page for h in hits), len(hits)),
        "assessed_any_gold_sentence_rate": ratio(sum(h.any_sentence for h in hits), len(hits)),
        "assessed_complete_gold_set_rate": ratio(sum(h.complete_set for h in hits), len(hits)),
        "limitations": [
            "Mapped FEVER NOT ENOUGH INFO and model abstention are not logically equivalent.",
            "Gold evidence alignment considers assessed sentences only; "
            "it does not measure raw retrieval recall.",
            "Evidence comes from one Wikipedia-derived corpus; "
            "independent corroboration is untested.",
            "Per-evidence NLI probabilities are not calibrated claim-level probabilities.",
            "A small diagnostic sample is not a population-level performance estimate.",
        ],
    }


def build_failure_rows(cases: Iterable[BenchmarkCase]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for case in cases:
        if case.mapped_label == case.example.label:
            continue
        hit = evidence_hit(case)
        if case.mapped_label == "CONFLICT":
            category = "CONFLICTING_PREDICTION"
        elif not case.decided:
            category = (
                "ABSTENTION_ON_DECISIVE_GOLD"
                if case.example.label != "NOT ENOUGH INFO"
                else "NEI_ABSTENTION"
            )
        else:
            category = "WRONG_DECISIVE_VERDICT"
        flags: list[str] = []
        if hit is not None:
            if not hit.any_page:
                flags.append("GOLD_PAGE_NOT_ASSESSED")
            elif not hit.any_sentence:
                flags.append("GOLD_SENTENCE_NOT_ASSESSED")
            elif not hit.complete_set:
                flags.append("GOLD_SET_INCOMPLETE_IN_ASSESSED")
        if not any(
            evidence.accepted and evidence.nli_label in ("ENTAILMENT", "CONTRADICTION")
            for evidence in case.evidence
        ):
            flags.append("NO_ACCEPTED_DECISIVE_NLI")
        if any(
            not evidence.accepted and evidence.nli_label in ("ENTAILMENT", "CONTRADICTION")
            for evidence in case.evidence
        ):
            flags.append("DECISIVE_LABEL_BELOW_THRESHOLD")
        if "ENTITY_VARIANT_MISMATCH" in case.exclusions:
            flags.append("ENTITY_VARIANT_FILTER_APPLIED")
        rows.append(
            {
                "claim_id": case.example.claim_id,
                "gold_label": case.example.label,
                "prediction": case.mapped_label,
                "failure_type": category,
                "diagnostic_flags": ";".join(flags),
                "gold_sentence_in_assessed": hit.any_sentence if hit else None,
                "gold_complete_set_in_assessed": hit.complete_set if hit else None,
                "assessed_count": case.assessed_count,
                "excluded_count": case.excluded_count,
                "claim": case.example.claim,
            }
        )
    return rows

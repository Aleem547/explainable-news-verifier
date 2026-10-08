"""Phase 8D: reproducible, CPU-sequential evaluation of the Phase 8C pipeline.

Run as a module from the Windows project root:
    uv run python -m scripts.evaluation.evaluate_fever_verification --dry-run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import polars as pl

from ml.verification.benchmark import (
    BenchmarkCase,
    BenchmarkExample,
    EvidenceKey,
    EvidenceObservation,
    build_failure_rows,
    select_balanced_examples,
    summarize_benchmark,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLAIMS = ROOT / "data" / "processed" / "fever" / "claims.parquet"
DEFAULT_GOLD = ROOT / "data" / "processed" / "fever" / "resolved_evidence.parquet"
DEFAULT_REPORTS = ROOT / "reports" / "evaluation"


def load_examples(path: Path, split: str) -> list[BenchmarkExample]:
    if not path.is_file():
        raise FileNotFoundError(f"FEVER claims not found: {path}")
    scan = pl.scan_parquet(path)
    expected = {"claim_id", "split", "label", "claim"}
    missing = expected - set(scan.collect_schema().names())
    if missing:
        raise ValueError(f"FEVER claims.parquet missing columns: {sorted(missing)}")
    frame = (
        scan.filter(pl.col("split") == split)
        .select("claim_id", "split", "label", "claim")
        .collect()
    )
    if frame.is_empty():
        raise ValueError(f"No FEVER claims for split {split!r}")
    return [
        BenchmarkExample(
            claim_id=int(row["claim_id"]),
            split=str(row["split"]),
            label=str(row["label"]),
            claim=str(row["claim"]),
        )
        for row in frame.iter_rows(named=True)
    ]


def load_gold_sets(
    path: Path, examples: list[BenchmarkExample]
) -> dict[tuple[str, int], tuple[frozenset[EvidenceKey], ...]]:
    """Keep only completely resolved evidence sets, never partial gold sets."""
    if not path.is_file():
        print(f"Gold annotations not found: {path} (gold-hit metrics will be unavailable)")
        return {}
    scan = pl.scan_parquet(path)
    required = {"claim_id", "split", "evidence_set_id", "wiki_page", "sentence_id", "resolved"}
    missing = required - set(scan.collect_schema().names())
    if missing:
        raise ValueError(f"Gold evidence parquet missing columns: {sorted(missing)}")
    ids = [row.claim_id for row in examples]
    split = examples[0].split
    frame = (
        scan.filter((pl.col("split") == split) & pl.col("claim_id").is_in(ids))
        .select(sorted(required))
        .collect()
    )
    groups: dict[tuple[str, int, int], set[EvidenceKey]] = {}
    invalid_groups: set[tuple[str, int, int]] = set()
    for row in frame.iter_rows(named=True):
        group = (str(row["split"]), int(row["claim_id"]), int(row["evidence_set_id"]))
        groups.setdefault(group, set())
        page = row["wiki_page"]
        sentence = row["sentence_id"]
        if not row["resolved"] or page is None or sentence is None or not str(page).strip():
            invalid_groups.add(group)
        else:
            groups[group].add(EvidenceKey(str(page), int(sentence)))
    result: dict[tuple[str, int], list[frozenset[EvidenceKey]]] = {}
    for (group_split, claim_id, set_id), refs in groups.items():
        if (group_split, claim_id, set_id) in invalid_groups or not refs:
            continue
        result.setdefault((group_split, claim_id), []).append(frozenset(refs))
    return {
        key: tuple(sorted(set(sets), key=lambda refs: sorted(refs))) for key, sets in result.items()
    }


def file_identity(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }


def code_hashes() -> dict[str, str]:
    relative_paths = (
        "ml/verification/evidence_pipeline.py",
        "ml/verification/evidence_quality.py",
        "ml/verification/entity_relevance.py",
        "ml/verification/evidence_aggregation.py",
        "ml/verification/nli_inference.py",
        "ml/retrieval/pipeline.py",
        "ml/verification/benchmark.py",
        "apps/api/services/retrieval.py",
        "apps/api/services/verification.py",
        "scripts/evaluation/evaluate_fever_verification.py",
    )
    return {
        rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        for rel in relative_paths
        if (ROOT / rel).is_file()
    }


def to_case(example: BenchmarkExample, top_k: int) -> BenchmarkCase:
    # This is the same lazily loaded pipeline as POST /api/v1/verify.
    # Only the claim and top_k enter the inference call: NO gold labels/sets.
    from apps.api.services.verification import run_verification

    prediction = run_verification(example.claim, top_k=top_k)
    return BenchmarkCase(
        example=example,
        verdict=str(prediction.verdict),
        latency_ms=prediction.latency_ms,
        retrieved_count=prediction.retrieved_count,
        assessed_count=prediction.assessed_count,
        excluded_count=prediction.quality_excluded_count,
        aggregation_reason=str(prediction.aggregation_reason),
        evidence=tuple(
            EvidenceObservation(
                page_id=item.page_id,
                sentence_id=item.sentence_id,
                text=item.text,
                nli_label=item.nli_label,
                nli_confidence=item.nli_confidence,
                accepted=item.accepted,
                contribution_role=str(item.contribution_role),
            )
            for item in prediction.evidence
        ),
        exclusions=tuple(str(item.reason) for item in prediction.quality_exclusions),
    )


def report_markdown(metrics: dict[str, Any], run_name: str) -> str:
    lines = [
        f"# Phase 8D evaluation — {run_name}",
        "",
        "**Diagnostic benchmark; not a production reliability certification.**",
        "",
        f"- Evaluated claims: {metrics['total_cases']}",
        f"- FEVER label agreement: {metrics['benchmark_label_agreement']}",
        f"- Macro F1 (three FEVER classes): {metrics['macro_f1']}",
        f"- Decision coverage: {metrics['decision_coverage']}",
        f"- Decided-only accuracy: {metrics['decided_accuracy']}",
        f"- Conflicting outcomes: {metrics['conflicting_count']}",
        f"- Mean inference latency: {metrics['mean_latency_ms']} ms",
        "",
        "## Assessed-evidence gold alignment",
        "",
        f"- Gold-annotated cases: {metrics['gold_annotated_cases']}",
        f"- Any gold page in assessed evidence: {metrics['assessed_any_gold_page_rate']}",
        f"- Any gold sentence in assessed evidence: {metrics['assessed_any_gold_sentence_rate']}",
        (
            "- Complete gold evidence set in assessed evidence: "
            f"{metrics['assessed_complete_gold_set_rate']}"
        ),
        "",
        "## Per-class metrics",
        "",
        "| Gold label | Count | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, row in metrics["per_class"].items():
        lines.append(
            f"| {label} | {row['support']} | {row['precision']} | {row['recall']} | {row['f1']} |"
        )
    lines.extend(["", "## Important limitations", ""])
    lines.extend(f"- {note}" for note in metrics["limitations"])
    lines.extend(
        [
            "",
            "This project has previously inspected FEVER test diagnostics; do not describe "
            "this as a pristine blind final holdout.",
            "Use failure reports for diagnosis. Tuning on test errors invalidates "
            "future test estimates.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("test", "validation"), default="test")
    parser.add_argument("--max-examples", type=int, default=12)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--claims-parquet", type=Path, default=DEFAULT_CLAIMS)
    parser.add_argument("--gold-parquet", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.top_k <= 20:
        parser.error("--top-k must be between 1 and 20")
    if args.max_examples < 3:
        parser.error("--max-examples must be at least 3")

    examples = select_balanced_examples(
        load_examples(args.claims_parquet, args.split),
        max_examples=args.max_examples,
        seed=args.seed,
    )
    gold = load_gold_sets(args.gold_parquet, examples)
    examples = [
        replace(example, gold_sets=gold.get((example.split, example.claim_id), ()))
        for example in examples
    ]
    selection = [
        {"claim_id": ex.claim_id, "split": ex.split, "gold_label": ex.label, "claim": ex.claim}
        for ex in examples
    ]
    selection_digest = hashlib.sha256(
        json.dumps(selection, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    print(f"FEVER split: {args.split}")
    print(f"Balanced selection: {len(examples)} claims / seed={args.seed}")
    print(f"Gold label counts: {dict(Counter(ex.label for ex in examples))}")
    print(f"Cases with complete gold annotations: {sum(bool(ex.gold_sets) for ex in examples)}")
    print(f"Selection SHA256: {selection_digest}")
    if args.dry_run:
        print("Dry run complete: models were NOT loaded and no benchmark report was written.")
        return

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"phase8d_{args.split}_{len(examples)}_seed{args.seed}_{stamp}"
    report_dir = args.reports_dir / run_name
    report_dir.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, object] = {
        "run_name": run_name,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "split": args.split,
        "max_examples": args.max_examples,
        "selected_examples": len(examples),
        "seed": args.seed,
        "top_k": args.top_k,
        "selection_sha256": selection_digest,
        "claim_file": file_identity(args.claims_parquet),
        "gold_file": file_identity(args.gold_parquet),
        "dvc_pointer": file_identity(ROOT / "data" / "processed" / "fever.dvc"),
        "model_artifacts": {
            name: file_identity(
                ROOT / "models" / "nli_verifier" / "nli-deberta-v3-small_fever_nli_30k" / name
            )
            for name in ("config.json", "calibration.json", "model.safetensors")
        },
        "code_sha256": code_hashes(),
        "label_visibility": (
            "Gold labels/annotations used for scoring only, never as inference inputs"
        ),
        "status": "RUNNING",
    }
    (report_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (report_dir / "selection.json").write_text(
        json.dumps(selection, indent=2, ensure_ascii=True), encoding="utf-8"
    )

    completed: list[BenchmarkCase] = []
    try:
        with (report_dir / "cases.jsonl").open("w", encoding="utf-8") as handle:
            for index, example in enumerate(examples, start=1):
                print(
                    f"[{index}/{len(examples)}] claim_id={example.claim_id} gold={example.label}",
                    flush=True,
                )
                case = to_case(example, top_k=args.top_k)
                completed.append(case)
                record = {
                    "claim_id": example.claim_id,
                    "split": example.split,
                    "claim": example.claim,
                    "gold_label": example.label,
                    "gold_sets": [
                        [asdict(ref) for ref in sorted(refs)] for refs in example.gold_sets
                    ],
                    "verdict": case.verdict,
                    "mapped_label": case.mapped_label,
                    "latency_ms": case.latency_ms,
                    "retrieved_count": case.retrieved_count,
                    "assessed_count": case.assessed_count,
                    "excluded_count": case.excluded_count,
                    "aggregation_reason": case.aggregation_reason,
                    "exclusions": list(case.exclusions),
                    "evidence": [asdict(item) for item in case.evidence],
                }
                handle.write(json.dumps(record, ensure_ascii=True) + "\n")
                handle.flush()
                print(
                    f"    verdict={case.verdict}, assessed={case.assessed_count}, "
                    f"latency={case.latency_ms:.0f}ms"
                )
    except Exception as exc:
        manifest["status"] = "FAILED_PARTIAL"
        manifest["completed_cases"] = len(completed)
        manifest["failure"] = f"{type(exc).__name__}: {exc}"
        (report_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Evaluation stopped after {len(completed)} cases. Partial data: {report_dir}")
        raise

    metrics = summarize_benchmark(completed)
    failure_rows = build_failure_rows(completed)
    (report_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (report_dir / "REPORT.md").write_text(report_markdown(metrics, run_name), encoding="utf-8")
    with (report_dir / "confusion_matrix.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        matrix_writer = csv.writer(handle)
        labels = ("SUPPORTS", "REFUTES", "NOT ENOUGH INFO", "CONFLICT")
        matrix_writer.writerow(("gold_label", *labels))
        confusion = cast(dict[str, dict[str, int]], metrics["confusion_matrix"])
        for gold_label, counts in confusion.items():
            matrix_writer.writerow((gold_label, *(counts[label] for label in labels)))
    fields = (
        "claim_id",
        "gold_label",
        "prediction",
        "failure_type",
        "diagnostic_flags",
        "gold_sentence_in_assessed",
        "gold_complete_set_in_assessed",
        "assessed_count",
        "excluded_count",
        "claim",
    )
    with (report_dir / "failures.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        failure_writer = csv.DictWriter(handle, fieldnames=fields)
        failure_writer.writeheader()
        failure_writer.writerows(failure_rows)
    manifest["status"] = "COMPLETE"
    manifest["completed_cases"] = len(completed)
    (report_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("\nPHASE 8D EVALUATION COMPLETE")
    print(f"Benchmark agreement: {metrics['benchmark_label_agreement']}")
    print(f"Macro F1: {metrics['macro_f1']}")
    print(f"Decision coverage: {metrics['decision_coverage']}")
    print(f"Decided-only accuracy: {metrics['decided_accuracy']}")
    print(f"Assessment-based complete-gold-set rate: {metrics['assessed_complete_gold_set_rate']}")
    print(f"Report directory: {report_dir}")


if __name__ == "__main__":
    main()

import json
from pathlib import Path
from typing import Any

from scripts.evaluation.compare_fever_nli_models import (
    PROJECT_ROOT,
    evaluate_model,
    load_validation_data,
)

MODELS = {
    "deberta_15k": (
        PROJECT_ROOT / "models" / "nli_verifier" / "nli-deberta-v3-small_fever_nli_15k"
    ),
    "deberta_30k": (
        PROJECT_ROOT / "models" / "nli_verifier" / "nli-deberta-v3-small_fever_nli_30k"
    ),
}

OUTPUT_PATH = PROJECT_ROOT / "data" / "metadata" / "fever_deberta_15k_vs_30k_comparison.json"


def main() -> None:
    print("Loading full FEVER validation dataset...")

    premises, claims, labels = load_validation_data()

    print(f"Validation examples: {len(labels):,}")

    results: dict[str, dict[str, Any]] = {}

    for name, model_path in MODELS.items():
        results[name] = evaluate_model(
            model_name=name,
            model_directory=Path(model_path),
            premises=premises,
            claims=claims,
            labels=labels,
            batch_size=16,
            max_length=256,
        )

    winner = max(
        results,
        key=lambda name: float(results[name]["metrics"]["macro_f1"]),
    )

    manifest = {
        "dataset": "fever",
        "split": "validation",
        "validation_examples": len(labels),
        "selection_metric": "macro_f1",
        "results": results,
        "winner": winner,
    }

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_PATH.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print("FINAL DEBERTA COMPARISON")
    print("=" * 60)

    for name, result in results.items():
        metrics = result["metrics"]

        print(f"\n{name}")
        print(f"Accuracy: {metrics['accuracy']:.4%}")
        print(f"Macro F1: {metrics['macro_f1']:.4f}")
        print(f"Macro Precision: {metrics['macro_precision']:.4f}")
        print(f"Macro Recall: {metrics['macro_recall']:.4f}")

    print(f"\nWinner: {winner}")
    print(f"Manifest: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

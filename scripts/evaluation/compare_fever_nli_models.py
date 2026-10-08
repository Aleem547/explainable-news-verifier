import json
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import polars as pl
import torch
from sklearn import metrics as sklearn_metrics  # type: ignore[import-untyped]
from transformers import (
    AutoConfig,
    AutoModelForSequenceClassification,
    AutoTokenizer,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATASET_PATH = PROJECT_ROOT / "data" / "processed" / "fever" / "nli_pairs_final.parquet"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_nli_model_comparison_manifest.json"


MODELS = {
    "distilbert_30k": (
        PROJECT_ROOT / "models" / "nli_verifier" / "distilbert-base-uncased_fever_nli_30k"
    ),
    "deberta_v3_small_15k": (
        PROJECT_ROOT / "models" / "nli_verifier" / "nli-deberta-v3-small_fever_nli_15k"
    ),
}


PROJECT_LABEL_TO_ID = {
    "entailment": 0,
    "contradiction": 1,
    "neutral": 2,
}


PROJECT_ID_TO_LABEL = {
    0: "ENTAILMENT",
    1: "CONTRADICTION",
    2: "NEUTRAL",
}


def normalize_label(
    label: str,
) -> str:
    return label.strip().lower().replace("-", "_").replace(" ", "_")


def build_model_to_project_mapping(
    model_directory: Path,
) -> dict[int, int]:
    config = AutoConfig.from_pretrained(str(model_directory))

    label2id = config.label2id

    if not label2id:
        raise ValueError(f"Model config has no label2id mapping: {model_directory}")

    normalized = {
        normalize_label(str(label_name)): int(label_id)
        for (
            label_name,
            label_id,
        ) in label2id.items()
    }

    required = {
        "entailment",
        "contradiction",
        "neutral",
    }

    if not required.issubset(normalized):
        raise ValueError(f"Model does not expose semantic NLI labels: {label2id}")

    model_to_project: dict[
        int,
        int,
    ] = {}

    for semantic_label in required:
        model_label_id = normalized[semantic_label]

        project_label_id = PROJECT_LABEL_TO_ID[semantic_label]

        model_to_project[model_label_id] = project_label_id

    return model_to_project


def load_validation_data() -> tuple[
    list[str],
    list[str],
    np.ndarray,
]:
    frame = (
        pl.scan_parquet(DATASET_PATH)
        .filter(pl.col("split") == "validation")
        .select(
            [
                "premise",
                "claim",
                "nli_label_id",
            ]
        )
        .sort(
            [
                "claim",
                "premise",
            ]
        )
        .collect()
    )

    if frame.is_empty():
        raise ValueError("Validation split is empty.")

    premises = [str(value) for value in frame["premise"].to_list()]

    claims = [str(value) for value in frame["claim"].to_list()]

    labels = np.asarray(
        frame["nli_label_id"].to_list(),
        dtype=np.int64,
    )

    return (
        premises,
        claims,
        labels,
    )


def evaluate_model(
    *,
    model_name: str,
    model_directory: Path,
    premises: list[str],
    claims: list[str],
    labels: np.ndarray,
    batch_size: int = 16,
    max_length: int = 256,
) -> dict[str, Any]:
    if not model_directory.exists():
        raise FileNotFoundError(f"Model directory does not exist: {model_directory}")

    print()
    print("=" * 70)

    print(f"Evaluating: {model_name}")

    print(f"Model: {model_directory}")

    model_to_project = build_model_to_project_mapping(model_directory)

    print("Model → project labels:")

    for model_id in sorted(model_to_project):
        project_id = model_to_project[model_id]

        print(f"  model {model_id} → project {project_id} ({PROJECT_ID_TO_LABEL[project_id]})")

    tokenizer = AutoTokenizer.from_pretrained(
        str(model_directory),
        use_fast=True,
    )

    model = AutoModelForSequenceClassification.from_pretrained(str(model_directory))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model.to(device)

    model.eval()

    predictions: list[int] = []
    confidences: list[float] = []

    total_examples = len(premises)

    total_batches = (total_examples + batch_size - 1) // batch_size

    started = perf_counter()

    with torch.inference_mode():
        for batch_index in range(total_batches):
            start = batch_index * batch_size

            end = min(
                start + batch_size,
                total_examples,
            )

            batch_premises = premises[start:end]

            batch_claims = claims[start:end]

            encoded = tokenizer(
                batch_premises,
                batch_claims,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )

            model_inputs = {key: value.to(device) for key, value in encoded.items()}

            outputs = model(**model_inputs)

            probabilities = torch.softmax(
                outputs.logits,
                dim=-1,
            )

            model_predictions = (
                torch.argmax(
                    probabilities,
                    dim=-1,
                )
                .cpu()
                .tolist()
            )

            batch_confidences = (
                torch.max(
                    probabilities,
                    dim=-1,
                )
                .values.cpu()
                .tolist()
            )

            for model_label_id in model_predictions:
                predictions.append(model_to_project[int(model_label_id)])

            confidences.extend(float(value) for value in batch_confidences)

            processed = end

            if (batch_index + 1) % 100 == 0:
                print(f"Processed {processed:,} / {total_examples:,}")

    elapsed_seconds = perf_counter() - started

    prediction_array = np.asarray(
        predictions,
        dtype=np.int64,
    )

    accuracy = sklearn_metrics.accuracy_score(
        labels,
        prediction_array,
    )

    macro_f1 = sklearn_metrics.f1_score(
        labels,
        prediction_array,
        average="macro",
    )

    weighted_f1 = sklearn_metrics.f1_score(
        labels,
        prediction_array,
        average="weighted",
    )

    macro_precision = sklearn_metrics.precision_score(
        labels,
        prediction_array,
        average="macro",
        zero_division=0,
    )

    macro_recall = sklearn_metrics.recall_score(
        labels,
        prediction_array,
        average="macro",
        zero_division=0,
    )

    per_class_f1 = sklearn_metrics.f1_score(
        labels,
        prediction_array,
        labels=[
            0,
            1,
            2,
        ],
        average=None,
        zero_division=0,
    )

    confusion_matrix = sklearn_metrics.confusion_matrix(
        labels,
        prediction_array,
        labels=[
            0,
            1,
            2,
        ],
    )

    mean_confidence = float(
        np.mean(
            np.asarray(
                confidences,
                dtype=np.float64,
            )
        )
    )

    examples_per_second = total_examples / elapsed_seconds

    result: dict[
        str,
        Any,
    ] = {
        "model": model_name,
        "model_directory": str(model_directory.relative_to(PROJECT_ROOT)),
        "examples": total_examples,
        "device": str(device),
        "metrics": {
            "accuracy": float(accuracy),
            "macro_f1": float(macro_f1),
            "weighted_f1": float(weighted_f1),
            "macro_precision": float(macro_precision),
            "macro_recall": float(macro_recall),
            "entailment_f1": float(per_class_f1[0]),
            "contradiction_f1": float(per_class_f1[1]),
            "neutral_f1": float(per_class_f1[2]),
        },
        "mean_confidence": (mean_confidence),
        "elapsed_seconds": float(elapsed_seconds),
        "examples_per_second": float(examples_per_second),
        "confusion_matrix": (confusion_matrix.tolist()),
        "model_to_project_label_id": {
            str(model_id): project_id
            for (
                model_id,
                project_id,
            ) in (model_to_project.items())
        },
    }

    print()
    print(f"Accuracy: {accuracy:.4%}")

    print(f"Macro F1: {macro_f1:.4f}")

    print(f"Macro Precision: {macro_precision:.4f}")

    print(f"Macro Recall: {macro_recall:.4f}")

    print()
    print("Per-class F1:")

    print(f"  ENTAILMENT: {per_class_f1[0]:.4f}")

    print(f"  CONTRADICTION: {per_class_f1[1]:.4f}")

    print(f"  NEUTRAL: {per_class_f1[2]:.4f}")

    print()
    print("Confusion matrix:")

    print(confusion_matrix)

    print()
    print(f"Evaluation time: {elapsed_seconds:.2f}s")

    print(f"Examples/sec: {examples_per_second:.2f}")

    return result


def main() -> None:
    if not DATASET_PATH.exists():
        raise FileNotFoundError("Final FEVER NLI dataset does not exist.")

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("Loading full clean validation split...")

    (
        premises,
        claims,
        labels,
    ) = load_validation_data()

    print(f"Validation examples: {len(labels):,}")

    results: dict[
        str,
        dict[str, Any],
    ] = {}

    for (
        model_name,
        model_directory,
    ) in MODELS.items():
        results[model_name] = evaluate_model(
            model_name=model_name,
            model_directory=(model_directory),
            premises=premises,
            claims=claims,
            labels=labels,
        )

    winner = max(
        results,
        key=lambda name: results[name]["metrics"]["macro_f1"],
    )

    manifest: dict[
        str,
        Any,
    ] = {
        "dataset": "fever",
        "stage": ("nli_full_validation_comparison"),
        "split": "validation",
        "evaluated_examples": len(labels),
        "selection_metric": ("macro_f1"),
        "winner": winner,
        "results": results,
    }

    MANIFEST_PATH.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 70)

    print("FINAL COMPARISON")

    print("=" * 70)

    for (
        model_name,
        result,
    ) in results.items():
        metrics = result["metrics"]

        print(f"{model_name}:")

        print(f"  Accuracy: {metrics['accuracy']:.4%}")

        print(f"  Macro F1: {metrics['macro_f1']:.4f}")

    print()
    print(f"Winner: {winner}")

    print(f"Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()

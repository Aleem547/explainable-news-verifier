import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl
import torch
from sklearn import metrics as sklearn_metrics  # type: ignore[import-untyped]
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATASET_PATH = PROJECT_ROOT / "data" / "processed" / "fever" / "claim_classification.parquet"

DEFAULT_MODEL_DIRECTORY = (
    PROJECT_ROOT / "models" / "claim_classifier" / "distilbert_fever_balanced_30k"
)

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

RESULTS_PATH = (
    PROJECT_ROOT / "data" / "processed" / "fever" / "claim_classifier_test_results.parquet"
)

MANIFEST_PATH = METADATA_DIRECTORY / "fever_claim_classifier_test_manifest.json"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Evaluate the frozen FEVER claim classifier on the test split.")
    )

    parser.add_argument(
        "--model-directory",
        type=Path,
        default=DEFAULT_MODEL_DIRECTORY,
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
    )

    parser.add_argument(
        "--max-length",
        type=int,
        default=128,
    )

    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()

    model_directory = arguments.model_directory.resolve()

    if not model_directory.exists():
        raise FileNotFoundError(f"Model directory not found: {model_directory}")

    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Classification dataset not found: {DATASET_PATH}")

    print(f"Loading model: {model_directory}")

    tokenizer = AutoTokenizer.from_pretrained(str(model_directory))

    model = AutoModelForSequenceClassification.from_pretrained(str(model_directory))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model.to(device)
    model.eval()

    print(f"Device: {device}")

    frame = (
        pl.scan_parquet(DATASET_PATH)
        .filter(pl.col("split") == "test")
        .select(
            [
                "claim_id",
                "claim",
                "label",
                "label_id",
            ]
        )
        .sort("claim_id")
        .collect()
    )

    if frame.is_empty():
        raise ValueError("No FEVER test rows found.")

    print(f"Test examples: {frame.height:,}")

    predictions: list[int] = []
    confidences: list[float] = []

    claims = frame["claim"].to_list()

    total_batches = (len(claims) + arguments.batch_size - 1) // arguments.batch_size

    with torch.inference_mode():
        for batch_index in range(total_batches):
            start = batch_index * arguments.batch_size

            end = min(
                start + arguments.batch_size,
                len(claims),
            )

            batch_claims = claims[start:end]

            encoded = tokenizer(
                batch_claims,
                padding=True,
                truncation=True,
                max_length=(arguments.max_length),
                return_tensors="pt",
            )

            encoded = {key: value.to(device) for key, value in encoded.items()}

            outputs = model(**encoded)

            probabilities = torch.softmax(
                outputs.logits,
                dim=-1,
            )

            batch_predictions = torch.argmax(
                probabilities,
                dim=-1,
            )

            batch_confidences = torch.max(
                probabilities,
                dim=-1,
            ).values

            predictions.extend(int(value) for value in batch_predictions.cpu())

            confidences.extend(float(value) for value in batch_confidences.cpu())

            if (batch_index + 1) % 50 == 0:
                print(f"Processed {end:,} / {len(claims):,}")

    labels = np.asarray(
        frame["label_id"].to_list(),
        dtype=np.int64,
    )

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

    confusion_matrix = sklearn_metrics.confusion_matrix(
        labels,
        prediction_array,
        labels=[
            0,
            1,
            2,
        ],
    )

    result_frame = frame.with_columns(
        [
            pl.Series(
                "prediction_id",
                predictions,
            ),
            pl.Series(
                "confidence",
                confidences,
            ),
        ]
    )

    result_frame.write_parquet(
        RESULTS_PATH,
        compression="zstd",
    )

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": ("claim_classifier_final_test"),
        "model_directory": str(model_directory.relative_to(PROJECT_ROOT)),
        "device": str(device),
        "test_examples": (frame.height),
        "metrics": {
            "accuracy": float(accuracy),
            "macro_f1": float(macro_f1),
            "weighted_f1": float(weighted_f1),
            "macro_precision": float(macro_precision),
            "macro_recall": float(macro_recall),
        },
        "confusion_matrix": (confusion_matrix.tolist()),
        "results": str(RESULTS_PATH.relative_to(PROJECT_ROOT)),
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
    print("Final FEVER test evaluation complete.")

    print()
    print(f"Accuracy: {accuracy:.4%}")

    print(f"Macro F1: {macro_f1:.4f}")

    print(f"Weighted F1: {weighted_f1:.4f}")

    print(f"Macro Precision: {macro_precision:.4f}")

    print(f"Macro Recall: {macro_recall:.4f}")

    print()

    print("Confusion matrix:")

    print(confusion_matrix)

    print()

    print(f"Results: {RESULTS_PATH}")

    print(f"Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()

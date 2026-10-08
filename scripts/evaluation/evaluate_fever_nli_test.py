import argparse
import json
from time import perf_counter
from typing import Any

import numpy as np
import polars as pl
from sklearn.metrics import confusion_matrix, f1_score  # type: ignore[import-untyped]

from ml.verification.calibration import (
    calibration_report,
    probabilities_from_logits,
)
from scripts.evaluation.calibrate_fever_nli import (
    CALIBRATION_PATH,
    DATASET_PATH,
    MODEL_DIRECTORY,
    PROJECT_ROOT,
    generate_logits,
    model_fingerprints,
    sha256_file,
)

CONFIDENCE_THRESHOLD = 0.90
MAX_LENGTH = 256

OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "processed" / "fever" / "nli_deberta_30k_test_predictions.parquet"
)

MANIFEST_PATH = PROJECT_ROOT / "data" / "metadata" / "fever_nli_final_test_manifest.json"

LABEL_NAMES = [
    "ENTAILMENT",
    "CONTRADICTION",
    "NEUTRAL",
]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Final frozen FEVER NLI test evaluation.")

    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
    )

    return parser.parse_args()


def load_calibration() -> tuple[float, dict[str, Any]]:
    if not CALIBRATION_PATH.is_file():
        raise FileNotFoundError(f"Calibration artifact missing: {CALIBRATION_PATH}")

    payload: dict[str, Any] = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))

    if payload.get("method") != "temperature_scaling":
        raise ValueError("Unexpected calibration method.")

    if payload.get("source_split") != "validation":
        raise ValueError("Calibration must originate from validation.")

    if payload.get("model") != MODEL_DIRECTORY.name:
        raise ValueError("Calibration model name does not match.")

    if payload.get("project_label_order") != LABEL_NAMES:
        raise ValueError("Calibration label ordering does not match.")

    current_fingerprints = model_fingerprints()

    if payload.get("model_fingerprints") != current_fingerprints:
        raise ValueError(
            "Model weights or configuration changed since calibration. Evaluation stopped."
        )

    temperature = float(payload["temperature"])

    if not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("Invalid calibration temperature.")

    return temperature, payload


def load_test_data() -> pl.DataFrame:
    if not DATASET_PATH.is_file():
        raise FileNotFoundError(DATASET_PATH)

    frame = (
        pl.scan_parquet(DATASET_PATH)
        .filter(pl.col("split") == "test")
        .select(
            [
                "example_id",
                "premise",
                "claim",
                "nli_label_id",
            ]
        )
        .sort("example_id")
        .collect()
    )

    if frame.is_empty():
        raise ValueError("Test split is empty.")

    if frame["example_id"].n_unique() != frame.height:
        raise ValueError("Duplicate example IDs in test split.")

    for column in frame.columns:
        if frame[column].null_count() > 0:
            raise ValueError(f"Null values in column: {column}")

    labels = frame["nli_label_id"].to_numpy()

    if not np.isin(labels, [0, 1, 2]).all():
        raise ValueError("Invalid test NLI labels.")

    return frame


def main() -> None:
    arguments = parse_arguments()

    if arguments.batch_size <= 0:
        raise ValueError("Batch size must be positive.")

    print("Verifying frozen model and calibration...")
    temperature, calibration = load_calibration()

    print(f"Selected model: {MODEL_DIRECTORY.name}")
    print(f"Temperature: {temperature:.6f}")
    print(f"Confidence threshold: {CONFIDENCE_THRESHOLD:.2f}")

    print()
    print("Loading untouched FEVER test split...")

    frame = load_test_data()

    premises = frame["premise"].to_list()
    claims = frame["claim"].to_list()

    labels = np.asarray(
        frame["nli_label_id"].to_list(),
        dtype=np.int64,
    )

    print(f"Test examples: {len(labels):,}")

    print()
    print("Running frozen model inference...")

    started = perf_counter()

    logits = generate_logits(
        premises,
        claims,
        batch_size=arguments.batch_size,
        max_length=MAX_LENGTH,
    )

    elapsed = perf_counter() - started

    if logits.shape != (len(labels), 3):
        raise ValueError("Unexpected model logit shape.")

    before: dict[str, Any] = calibration_report(
        logits,
        labels,
        temperature=1.0,
    )

    after: dict[str, Any] = calibration_report(
        logits,
        labels,
        temperature=temperature,
    )

    raw_predictions = np.argmax(logits, axis=1)

    probabilities = probabilities_from_logits(
        logits,
        temperature,
    )

    predictions = np.argmax(probabilities, axis=1)
    confidences = np.max(probabilities, axis=1)

    if not np.array_equal(raw_predictions, predictions):
        raise ValueError("Temperature scaling unexpectedly changed predictions.")

    accepted = confidences >= CONFIDENCE_THRESHOLD
    accepted_count = int(np.sum(accepted))

    accepted_accuracy = (
        float(np.mean(predictions[accepted] == labels[accepted])) if accepted_count > 0 else None
    )

    class_f1 = f1_score(
        labels,
        predictions,
        labels=[0, 1, 2],
        average=None,
        zero_division=0,
    )

    matrix = confusion_matrix(
        labels,
        predictions,
        labels=[0, 1, 2],
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

    predictions_frame = pl.DataFrame(
        {
            "example_id": frame["example_id"].to_list(),
            "gold_label_id": labels.tolist(),
            "prediction_label_id": predictions.tolist(),
            "confidence": confidences.tolist(),
            "accepted_at_0_90": accepted.tolist(),
            "prob_entailment": probabilities[:, 0].tolist(),
            "prob_contradiction": probabilities[:, 1].tolist(),
            "prob_neutral": probabilities[:, 2].tolist(),
        }
    )

    predictions_frame.write_parquet(
        OUTPUT_PATH,
        compression="zstd",
    )

    class_metrics = {LABEL_NAMES[index]: float(class_f1[index]) for index in range(3)}

    manifest: dict[str, Any] = {
        "stage": "phase_7d_final_nli_test",
        "dataset": "fever",
        "split": "test",
        "model": MODEL_DIRECTORY.name,
        "model_fingerprints": calibration["model_fingerprints"],
        "dataset_sha256": sha256_file(DATASET_PATH),
        "calibration_sha256": sha256_file(CALIBRATION_PATH),
        "temperature": temperature,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "max_length": MAX_LENGTH,
        "test_examples": len(labels),
        "inference_seconds": elapsed,
        "uncalibrated": before,
        "calibrated": after,
        "per_class_f1": class_metrics,
        "confusion_matrix": matrix.tolist(),
        "accepted_count": accepted_count,
        "accepted_coverage": float(np.mean(accepted)),
        "accepted_accuracy": accepted_accuracy,
        "predictions_file": str(OUTPUT_PATH.relative_to(PROJECT_ROOT)),
        "evaluation_scope": (
            "FEVER evidence-pair NLI, not end-to-end article-level fact verification."
        ),
    }

    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print()
    print("=" * 60)
    print("PHASE 7D - FINAL NLI TEST RESULTS")
    print("=" * 60)

    print(f"Examples: {len(labels):,}")
    print(f"Temperature: {temperature:.6f}")

    print()
    print("Before vs after calibration:")

    for metric in (
        "accuracy",
        "macro_f1",
        "nll",
        "ece_15_bins",
        "brier_score",
        "mean_confidence",
    ):
        print(f"{metric:20s} before={before[metric]:.5f}  after={after[metric]:.5f}")

    print()
    print("Per-class F1:")

    for label, score in class_metrics.items():
        print(f"  {label}: {score:.4f}")

    print()
    print("Confusion matrix:")
    print(matrix)

    print()
    print("Locked confidence threshold analysis:")

    print(f"Threshold: {CONFIDENCE_THRESHOLD:.2f}")
    print(f"Accepted: {accepted_count:,}")
    print(f"Coverage: {np.mean(accepted):.2%}")
    print(f"Accepted accuracy: {accepted_accuracy}")

    print()
    print(f"Inference duration: {elapsed:.2f}s")
    print(f"Predictions: {OUTPUT_PATH}")
    print(f"Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import polars as pl
import torch
from transformers import (
    AutoConfig,
    AutoModelForSequenceClassification,
    AutoTokenizer,
)

from ml.verification.calibration import (
    calibration_report,
    fit_temperature,
    stratified_calibration_split,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MODEL_DIRECTORY = PROJECT_ROOT / "models" / "nli_verifier" / "nli-deberta-v3-small_fever_nli_30k"

DATASET_PATH = PROJECT_ROOT / "data" / "processed" / "fever" / "nli_pairs_final.parquet"

LOGITS_PATH = (
    PROJECT_ROOT / "data" / "processed" / "fever" / "nli_deberta_30k_validation_logits.npz"
)

CACHE_METADATA_PATH = PROJECT_ROOT / "data" / "metadata" / "fever_nli_validation_logits_cache.json"

MANIFEST_PATH = PROJECT_ROOT / "data" / "metadata" / "fever_nli_calibration_manifest.json"

CALIBRATION_PATH = MODEL_DIRECTORY / "calibration.json"

PROJECT_LABELS = {
    "entailment": 0,
    "contradiction": 1,
    "neutral": 2,
}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate the selected FEVER NLI verifier.")

    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--reuse-logits",
        action="store_true",
        help="Reuse previously verified validation logits.",
    )

    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024 * 8),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def model_fingerprints() -> dict[str, str]:
    config_file = MODEL_DIRECTORY / "config.json"

    weight_files = sorted(
        [
            *MODEL_DIRECTORY.glob("*.safetensors"),
            *MODEL_DIRECTORY.glob("*.bin"),
        ]
    )

    if not config_file.is_file() or not weight_files:
        raise FileNotFoundError("Selected NLI model configuration or weights are missing.")

    return {path.name: sha256_file(path) for path in [config_file, *weight_files]}


def load_validation() -> tuple[list[str], list[str], np.ndarray, np.ndarray]:
    frame = (
        pl.scan_parquet(DATASET_PATH)
        .filter(pl.col("split") == "validation")
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
        raise ValueError("FEVER validation split is empty.")

    premises = frame["premise"].to_list()
    claims = frame["claim"].to_list()

    labels = np.asarray(
        frame["nli_label_id"].to_list(),
        dtype=np.int64,
    )

    example_ids = np.asarray(
        frame["example_id"].to_list(),
        dtype=np.int64,
    )

    return premises, claims, labels, example_ids


def model_logit_order() -> list[int]:
    config = AutoConfig.from_pretrained(str(MODEL_DIRECTORY))

    mapping = {str(name).strip().lower(): int(index) for name, index in config.label2id.items()}

    if set(mapping) != set(PROJECT_LABELS):
        raise ValueError(f"Unexpected checkpoint label mapping: {mapping}")

    order = [
        mapping["entailment"],
        mapping["contradiction"],
        mapping["neutral"],
    ]

    if sorted(order) != [0, 1, 2]:
        raise ValueError("Invalid model NLI label indices.")

    print("Model logit columns reordered into project label order.")
    print("Project labels: ENTAILMENT, CONTRADICTION, NEUTRAL")
    print(f"Model column order: {order}")

    return order


def generate_logits(
    premises: list[str],
    claims: list[str],
    *,
    batch_size: int,
    max_length: int,
) -> np.ndarray:
    if batch_size <= 0 or max_length <= 0:
        raise ValueError("Batch size and max length must be positive.")

    order = model_logit_order()

    tokenizer = AutoTokenizer.from_pretrained(
        str(MODEL_DIRECTORY),
        use_fast=True,
    )

    model = AutoModelForSequenceClassification.from_pretrained(str(MODEL_DIRECTORY))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model.to(device)
    model.eval()

    print(f"Device: {device}")

    batches: list[np.ndarray] = []
    total = len(premises)

    with torch.inference_mode():
        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)

            encoded = tokenizer(
                premises[start:end],
                claims[start:end],
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )

            inputs = {key: value.to(device) for key, value in encoded.items()}

            outputs = model(**inputs)

            batch_logits = outputs.logits.detach().cpu().numpy()[:, order]

            batches.append(np.asarray(batch_logits, dtype=np.float32))

            if end % 1600 == 0 or end == total:
                print(f"Processed {end:,} / {total:,}")

    return np.concatenate(batches, axis=0)


def main() -> None:
    arguments = parse_arguments()

    if not DATASET_PATH.is_file():
        raise FileNotFoundError(DATASET_PATH)

    if not MODEL_DIRECTORY.is_dir():
        raise FileNotFoundError(MODEL_DIRECTORY)

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOGITS_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("Loading clean FEVER validation split...")

    premises, claims, labels, example_ids = load_validation()

    print(f"Validation examples: {len(labels):,}")

    print("Checking model and dataset fingerprints...")

    cache_contract: dict[str, Any] = {
        "dataset_sha256": sha256_file(DATASET_PATH),
        "model_fingerprints": model_fingerprints(),
        "max_length": arguments.max_length,
        "label_order": [
            "ENTAILMENT",
            "CONTRADICTION",
            "NEUTRAL",
        ],
        "examples": len(labels),
    }

    inference_seconds: float | None = None

    if arguments.reuse_logits:
        if not LOGITS_PATH.is_file() or not CACHE_METADATA_PATH.is_file():
            raise FileNotFoundError("Cannot reuse logits: cache or metadata is missing.")

        saved_contract = json.loads(CACHE_METADATA_PATH.read_text(encoding="utf-8"))

        if saved_contract != cache_contract:
            raise ValueError(
                "Cached logits do not match the current model "
                "or dataset. Rerun without --reuse-logits."
            )

        with np.load(LOGITS_PATH, allow_pickle=False) as cached:
            logits = cached["logits"]
            cached_labels = cached["labels"]
            cached_ids = cached["example_ids"]

        if not np.array_equal(labels, cached_labels) or not np.array_equal(example_ids, cached_ids):
            raise ValueError("Cached row identities do not match.")

        print("Verified cached validation logits loaded.")

    else:
        print("Generating validation logits...")

        started = perf_counter()

        logits = generate_logits(
            premises,
            claims,
            batch_size=arguments.batch_size,
            max_length=arguments.max_length,
        )

        inference_seconds = perf_counter() - started

        np.savez_compressed(
            LOGITS_PATH,
            logits=logits,
            labels=labels,
            example_ids=example_ids,
        )

        CACHE_METADATA_PATH.write_text(
            json.dumps(cache_contract, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        print(f"Logits saved: {LOGITS_PATH}")

    if logits.shape != (len(labels), 3):
        raise ValueError("Incorrect cached or generated logit shape.")

    if not np.isfinite(logits).all():
        raise ValueError("Model produced non-finite logits.")

    calibration_ids, diagnostic_ids = stratified_calibration_split(
        labels,
        seed=arguments.seed,
    )

    calibration_logits = logits[calibration_ids]
    calibration_labels = labels[calibration_ids]

    diagnostic_logits = logits[diagnostic_ids]
    diagnostic_labels = labels[diagnostic_ids]

    print()
    print(f"Calibration rows: {len(calibration_ids):,}")
    print(f"Diagnostic rows: {len(diagnostic_ids):,}")

    print("Fitting temperature on calibration rows only...")

    temperature = fit_temperature(
        calibration_logits,
        calibration_labels,
    )

    print(f"Learned temperature: {temperature:.6f}")

    results: dict[str, Any] = {}

    for name, subset_logits, subset_labels in [
        ("calibration", calibration_logits, calibration_labels),
        ("diagnostic", diagnostic_logits, diagnostic_labels),
    ]:
        before = calibration_report(
            subset_logits,
            subset_labels,
            temperature=1.0,
        )

        after = calibration_report(
            subset_logits,
            subset_labels,
            temperature=temperature,
        )

        results[name] = {
            "before": before,
            "after": after,
        }

    diagnostic_before = results["diagnostic"]["before"]
    diagnostic_after = results["diagnostic"]["after"]

    calibration_config = {
        "method": "temperature_scaling",
        "temperature": temperature,
        "model": "nli-deberta-v3-small_fever_nli_30k",
        "project_label_order": [
            "ENTAILMENT",
            "CONTRADICTION",
            "NEUTRAL",
        ],
        "source_split": "validation",
        "calibration_rows": len(calibration_ids),
        "seed": arguments.seed,
        "model_fingerprints": cache_contract["model_fingerprints"],
    }

    CALIBRATION_PATH.write_text(
        json.dumps(calibration_config, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    manifest = {
        "dataset": "fever",
        "stage": "phase_7d_temperature_calibration",
        "selected_model": calibration_config["model"],
        "validation_rows": len(labels),
        "calibration_rows": len(calibration_ids),
        "diagnostic_rows": len(diagnostic_ids),
        "seed": arguments.seed,
        "temperature": temperature,
        "inference_seconds": inference_seconds,
        "results": results,
        "model_fingerprints": cache_contract["model_fingerprints"],
        "dataset_sha256": cache_contract["dataset_sha256"],
        "calibration_artifact": str(CALIBRATION_PATH),
        "logits_artifact": str(LOGITS_PATH),
        "selection_caveat": (
            "The full validation split was previously used for "
            "model selection; diagnostic metrics are not independent."
        ),
    }

    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print()
    print("=" * 60)
    print("PHASE 7D - CALIBRATION RESULTS")
    print("=" * 60)

    print(f"Temperature: {temperature:.6f}")
    print()

    for metric in (
        "accuracy",
        "macro_f1",
        "nll",
        "ece_15_bins",
        "brier_score",
        "mean_confidence",
    ):
        print(
            f"{metric:20s} "
            f"before={diagnostic_before[metric]:.5f}  "
            f"after={diagnostic_after[metric]:.5f}"
        )

    print()
    print("Diagnostic confidence / abstention analysis:")

    for row in diagnostic_after["selective_results"]:
        print(
            f"threshold={row['threshold']:.2f}  "
            f"coverage={row['coverage']:.2%}  "
            f"accepted_accuracy={row['accepted_accuracy']}"
        )

    print()
    print(f"Calibration config: {CALIBRATION_PATH}")
    print(f"Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import mlflow

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MODEL_DIRECTORY = (
    PROJECT_ROOT / "models" / "nli_verifier" / "distilbert-base-uncased_fever_nli_30k"
)

DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT
    / "data"
    / "metadata"
    / "distilbert-base-uncased_fever_nli_30k_training_manifest.json"
)

DEFAULT_TRACKING_URI = "http://127.0.0.1:5000"
DEFAULT_EXPERIMENT = "fever-evidence-verification"
DEFAULT_RUN_NAME = "distilbert-nli-balanced-30k"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register a FEVER NLI training run in MLflow.")

    parser.add_argument(
        "--model-directory",
        type=Path,
        default=DEFAULT_MODEL_DIRECTORY,
    )

    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
    )

    parser.add_argument(
        "--tracking-uri",
        default=DEFAULT_TRACKING_URI,
    )

    parser.add_argument(
        "--experiment",
        default=DEFAULT_EXPERIMENT,
    )

    parser.add_argument(
        "--run-name",
        default=DEFAULT_RUN_NAME,
    )

    return parser.parse_args()


def get_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        return result.stdout.strip()

    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
    ):
        return "unknown"


def load_manifest(
    path: Path,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(
        payload,
        dict,
    ):
        raise TypeError("Training manifest must contain a JSON object.")

    return payload


def numeric_metrics(
    payload: object,
) -> dict[str, float]:
    if not isinstance(
        payload,
        dict,
    ):
        return {}

    metrics: dict[str, float] = {}

    for key, value in payload.items():
        if isinstance(
            value,
            bool,
        ):
            continue

        if isinstance(
            value,
            (int, float),
        ):
            metrics[key] = float(value)

    return metrics


def main() -> None:
    arguments = parse_arguments()

    model_directory = arguments.model_directory.resolve()

    manifest_path = arguments.manifest.resolve()

    if not model_directory.exists():
        raise FileNotFoundError(f"Model directory not found: {model_directory}")

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    manifest = load_manifest(manifest_path)

    mlflow.set_tracking_uri(arguments.tracking_uri)

    mlflow.set_experiment(arguments.experiment)

    print("Registering FEVER evidence-verification run...")

    with mlflow.start_run(run_name=arguments.run_name) as run:
        mlflow.set_tags(
            {
                "dataset": "fever",
                "task": "natural_language_inference",
                "component": "evidence_verifier",
                "framework": "transformers",
                "stage": "phase_7_nli_baseline",
                "git_commit": get_git_commit(),
            }
        )

        parameter_names = (
            "model",
            "device",
            "epochs",
            "batch_size",
            "learning_rate",
            "max_length",
            "training_examples",
            "validation_examples",
            "balanced_training",
            "balanced_validation",
        )

        parameters: dict[
            str,
            str | int | float | bool,
        ] = {}

        for name in parameter_names:
            value = manifest.get(name)

            if isinstance(
                value,
                (str, int, float, bool),
            ):
                parameters[name] = value

        mlflow.log_params(parameters)

        train_metrics = numeric_metrics(manifest.get("train_metrics"))

        validation_metrics = numeric_metrics(manifest.get("validation_metrics"))

        if train_metrics:
            mlflow.log_metrics({f"train_{key}": value for key, value in train_metrics.items()})

        if validation_metrics:
            mlflow.log_metrics(validation_metrics)

        mlflow.log_artifact(
            str(manifest_path),
            artifact_path="metadata",
        )

        print("Uploading NLI model artifacts...")

        mlflow.log_artifacts(
            str(model_directory),
            artifact_path="model",
        )

        print()
        print("MLflow registration complete.")

        print(f"Run ID: {run.info.run_id}")


if __name__ == "__main__":
    main()

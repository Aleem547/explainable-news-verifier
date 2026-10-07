import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import mlflow

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MODEL_DIRECTORY = (
    PROJECT_ROOT / "models" / "claim_classifier" / "distilbert_fever_balanced_30k"
)

DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT / "data" / "metadata" / "fever_claim_classifier_training_manifest.json"
)

DEFAULT_TRACKING_URI = "http://127.0.0.1:5000"

DEFAULT_EXPERIMENT_NAME = "fever-claim-classification"

DEFAULT_RUN_NAME = "distilbert-balanced-30k"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Register an existing FEVER claim-classifier experiment with MLflow.")
    )

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
        type=str,
        default=DEFAULT_TRACKING_URI,
    )

    parser.add_argument(
        "--experiment",
        type=str,
        default=DEFAULT_EXPERIMENT_NAME,
    )

    parser.add_argument(
        "--run-name",
        type=str,
        default=DEFAULT_RUN_NAME,
    )

    return parser.parse_args()


def get_git_commit() -> str:
    try:
        result = subprocess.run(
            [
                "git",
                "rev-parse",
                "HEAD",
            ],
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
    manifest_path: Path,
) -> dict[str, Any]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Training manifest not found: {manifest_path}")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    if not isinstance(
        payload,
        dict,
    ):
        raise TypeError("Training manifest must contain a JSON object.")

    return payload


def numeric_metrics(
    payload: object,
    *,
    prefix: str,
) -> dict[str, float]:
    if not isinstance(
        payload,
        dict,
    ):
        return {}

    metrics: dict[
        str,
        float,
    ] = {}

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
            metrics[f"{prefix}{key}"] = float(value)

    return metrics


def main() -> None:
    arguments = parse_arguments()

    model_directory = arguments.model_directory.resolve()

    manifest_path = arguments.manifest.resolve()

    if not model_directory.exists():
        raise FileNotFoundError(f"Model directory not found: {model_directory}")

    manifest = load_manifest(manifest_path)

    mlflow.set_tracking_uri(arguments.tracking_uri)

    mlflow.set_experiment(arguments.experiment)

    git_commit = get_git_commit()

    print("Registering existing claim-classifier run...")

    print(f"MLflow: {arguments.tracking_uri}")

    print(f"Experiment: {arguments.experiment}")

    print(f"Run: {arguments.run_name}")

    print(f"Model: {model_directory}")

    with mlflow.start_run(run_name=arguments.run_name) as run:
        mlflow.set_tags(
            {
                "dataset": "fever",
                "task": ("claim_classification"),
                "framework": ("transformers"),
                "stage": ("phase_6_claim_baseline"),
                "git_commit": git_commit,
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
            "balanced_train_subset",
            "balanced_validation_subset",
        )

        parameters: dict[
            str,
            str | int | float | bool,
        ] = {}

        for parameter_name in parameter_names:
            value = manifest.get(parameter_name)

            if isinstance(
                value,
                (str, int, float, bool),
            ):
                parameters[parameter_name] = value

        mlflow.log_params(parameters)

        train_metrics = numeric_metrics(
            manifest.get("train_metrics"),
            prefix="",
        )

        validation_metrics = numeric_metrics(
            manifest.get("validation_metrics"),
            prefix="",
        )

        if train_metrics:
            mlflow.log_metrics(train_metrics)

        if validation_metrics:
            mlflow.log_metrics(validation_metrics)

        mlflow.log_artifact(
            str(manifest_path),
            artifact_path="metadata",
        )

        print("Uploading model artifacts to MLflow...")

        mlflow.log_artifacts(
            str(model_directory),
            artifact_path="model",
        )

        print()
        print("MLflow registration completed.")

        print(f"Run ID: {run.info.run_id}")

        print(f"Experiment ID: {run.info.experiment_id}")


if __name__ == "__main__":
    main()

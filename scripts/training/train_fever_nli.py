import argparse
import json
import re
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import Dataset
from transformers import (
    AutoConfig,
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    PretrainedConfig,
    Trainer,
    TrainingArguments,
)

from ml.verification.dataset import (
    FeverNliDataset,
)
from ml.verification.labels import (
    NLI_ID_TO_LABEL,
    NLI_LABEL_TO_ID,
)
from ml.verification.metrics import (
    compute_nli_metrics,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATASET_PATH = PROJECT_ROOT / "data" / "processed" / "fever" / "nli_pairs_final.parquet"

MODEL_ROOT = PROJECT_ROOT / "models" / "nli_verifier"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

DEFAULT_MODEL = "distilbert-base-uncased"


class LabelRemappedDataset(Dataset[dict[str, Any]]):
    def __init__(
        self,
        *,
        dataset: FeverNliDataset,
        project_to_model_label_id: dict[
            int,
            int,
        ],
    ) -> None:
        self.dataset = dataset

        self.project_to_model_label_id = project_to_model_label_id

    def __len__(self) -> int:
        return len(self.dataset)

    def __getitem__(
        self,
        index: int,
    ) -> dict[str, Any]:
        item = dict(self.dataset[index])

        project_label_id = int(item["labels"])

        try:
            model_label_id = self.project_to_model_label_id[project_label_id]

        except KeyError as exc:
            raise ValueError(
                f"No model label mapping for project label id {project_label_id}"
            ) from exc

        item["labels"] = model_label_id

        return item


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Train an evidence-conditioned FEVER NLI verifier.")
    )

    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
    )

    parser.add_argument(
        "--epochs",
        type=float,
        default=1.0,
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
    )

    parser.add_argument(
        "--learning-rate",
        type=float,
        default=2e-5,
    )

    parser.add_argument(
        "--max-length",
        type=int,
        default=256,
    )

    parser.add_argument(
        "--max-train-examples",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--max-validation-examples",
        type=int,
        default=None,
    )

    return parser.parse_args()


def safe_model_name(
    model_name: str,
) -> str:
    component = model_name.split("/")[-1]

    return re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        component,
    )


def build_run_name(
    *,
    model_name: str,
    max_train_examples: int | None,
) -> str:
    model_component = safe_model_name(model_name)

    if max_train_examples is None:
        size_component = "full"

    elif max_train_examples % 1000 == 0:
        size_component = f"{max_train_examples // 1000}k"

    else:
        size_component = str(max_train_examples)

    return f"{model_component}_fever_nli_{size_component}"


def normalize_label_name(
    label: str,
) -> str:
    return label.strip().lower().replace("-", "_").replace(" ", "_")


def semantic_checkpoint_mapping(
    config: PretrainedConfig,
) -> dict[str, int] | None:
    if not config.label2id:
        return None

    normalized_mapping = {
        normalize_label_name(str(label_name)): int(label_id)
        for (
            label_name,
            label_id,
        ) in config.label2id.items()
    }

    required_labels = {
        "entailment",
        "contradiction",
        "neutral",
    }

    if not required_labels.issubset(normalized_mapping):
        return None

    return {label: normalized_mapping[label] for label in required_labels}


def configure_model(
    model_name: str,
) -> tuple[
    torch.nn.Module,
    dict[int, int],
    dict[str, int],
]:
    config = AutoConfig.from_pretrained(model_name)

    checkpoint_mapping = semantic_checkpoint_mapping(config)

    project_name_to_id = {
        label.value.lower(): label_id
        for (
            label,
            label_id,
        ) in NLI_LABEL_TO_ID.items()
    }

    if checkpoint_mapping is not None:
        print()
        print("Semantic NLI checkpoint detected.")

        print("Preserving pretrained classification head.")

        print("Checkpoint label mapping:")

        for (
            label_name,
            label_id,
        ) in sorted(
            checkpoint_mapping.items(),
            key=lambda item: item[1],
        ):
            print(f"  {label_id} = {label_name.upper()}")

        project_to_model_label_id = {
            project_name_to_id["entailment"]: checkpoint_mapping["entailment"],
            project_name_to_id["contradiction"]: checkpoint_mapping["contradiction"],
            project_name_to_id["neutral"]: checkpoint_mapping["neutral"],
        }

        model = AutoModelForSequenceClassification.from_pretrained(
            model_name,
        )

        model_mapping = {
            label_name.upper(): label_id
            for (
                label_name,
                label_id,
            ) in checkpoint_mapping.items()
        }

        return (
            model,
            project_to_model_label_id,
            model_mapping,
        )

    print()
    print("Generic pretrained encoder detected.")

    print("Initializing a fresh 3-class NLI head.")

    id2label = {
        label_id: label.value
        for (
            label_id,
            label,
        ) in NLI_ID_TO_LABEL.items()
    }

    label2id = {
        label.value: label_id
        for (
            label,
            label_id,
        ) in NLI_LABEL_TO_ID.items()
    }

    config.num_labels = 3
    config.id2label = id2label
    config.label2id = label2id

    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        config=config,
    )

    project_to_model_label_id = {
        label_id: label_id
        for label_id in (
            0,
            1,
            2,
        )
    }

    model_mapping = {
        label.value: label_id
        for (
            label,
            label_id,
        ) in NLI_LABEL_TO_ID.items()
    }

    return (
        model,
        project_to_model_label_id,
        model_mapping,
    )


def main() -> None:
    arguments = parse_arguments()

    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Final NLI dataset does not exist: {DATASET_PATH}")

    MODEL_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_name = build_run_name(
        model_name=arguments.model,
        max_train_examples=(arguments.max_train_examples),
    )

    output_directory = MODEL_ROOT / run_name

    manifest_path = METADATA_DIRECTORY / f"{run_name}_training_manifest.json"

    print(f"Run name: {run_name}")

    print(f"Loading tokenizer: {arguments.model}")

    tokenizer = AutoTokenizer.from_pretrained(
        arguments.model,
        use_fast=True,
    )

    print("Loading FEVER NLI datasets...")

    base_train_dataset = FeverNliDataset(
        parquet_path=DATASET_PATH,
        split="train",
        tokenizer=tokenizer,
        max_length=(arguments.max_length),
        max_examples=(arguments.max_train_examples),
        balanced=(arguments.max_train_examples is not None),
        seed=42,
    )

    base_validation_dataset = FeverNliDataset(
        parquet_path=DATASET_PATH,
        split="validation",
        tokenizer=tokenizer,
        max_length=(arguments.max_length),
        max_examples=(arguments.max_validation_examples),
        balanced=(arguments.max_validation_examples is not None),
        seed=43,
    )

    print(f"Training examples: {len(base_train_dataset):,}")

    print(f"Validation examples: {len(base_validation_dataset):,}")

    print(f"Loading model: {arguments.model}")

    (
        model,
        project_to_model_label_id,
        model_label_mapping,
    ) = configure_model(arguments.model)

    print()
    print("Project → model label remapping:")

    for project_label_id in (
        0,
        1,
        2,
    ):
        project_label = NLI_ID_TO_LABEL[project_label_id]

        model_label_id = project_to_model_label_id[project_label_id]

        print(f"  {project_label.value} ({project_label_id}) → model id {model_label_id}")

    train_dataset = LabelRemappedDataset(
        dataset=(base_train_dataset),
        project_to_model_label_id=(project_to_model_label_id),
    )

    validation_dataset = LabelRemappedDataset(
        dataset=(base_validation_dataset),
        project_to_model_label_id=(project_to_model_label_id),
    )

    training_arguments = TrainingArguments(
        output_dir=str(output_directory),
        num_train_epochs=(arguments.epochs),
        per_device_train_batch_size=(arguments.batch_size),
        per_device_eval_batch_size=(arguments.batch_size),
        learning_rate=(arguments.learning_rate),
        weight_decay=0.01,
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_steps=50,
        load_best_model_at_end=True,
        metric_for_best_model=("macro_f1"),
        greater_is_better=True,
        save_total_limit=2,
        report_to="none",
        dataloader_num_workers=0,
        use_cpu=(not torch.cuda.is_available()),
        seed=42,
    )

    data_collator = DataCollatorWithPadding(tokenizer=tokenizer)

    trainer = Trainer(
        model=model,
        args=training_arguments,
        train_dataset=train_dataset,
        eval_dataset=(validation_dataset),
        data_collator=(data_collator),
        compute_metrics=(compute_nli_metrics),
    )

    print()
    print("Starting evidence-aware NLI training...")

    train_result = trainer.train()

    print()
    print("Running validation evaluation...")

    validation_metrics = trainer.evaluate()

    print()
    print("Saving trained model...")

    trainer.save_model(str(output_directory))

    tokenizer.save_pretrained(str(output_directory))

    manifest: dict[
        str,
        object,
    ] = {
        "dataset": "fever",
        "stage": ("evidence_conditioned_nli"),
        "run_name": run_name,
        "model": arguments.model,
        "device": ("cuda" if torch.cuda.is_available() else "cpu"),
        "epochs": (arguments.epochs),
        "batch_size": (arguments.batch_size),
        "learning_rate": (arguments.learning_rate),
        "max_length": (arguments.max_length),
        "training_examples": len(base_train_dataset),
        "validation_examples": len(base_validation_dataset),
        "balanced_training": (arguments.max_train_examples is not None),
        "balanced_validation": (arguments.max_validation_examples is not None),
        "project_label_mapping": {
            label.value: label_id
            for (
                label,
                label_id,
            ) in NLI_LABEL_TO_ID.items()
        },
        "model_label_mapping": (model_label_mapping),
        "project_to_model_label_id": {
            str(project_id): model_id
            for (
                project_id,
                model_id,
            ) in (project_to_model_label_id.items())
        },
        "train_metrics": (train_result.metrics),
        "validation_metrics": (validation_metrics),
        "output_directory": str(output_directory.relative_to(PROJECT_ROOT)),
    }

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print()
    print("NLI training complete.")

    print(f"Model: {output_directory}")

    print(f"Manifest: {manifest_path}")

    print()
    print("Validation metrics:")

    for (
        metric_name,
        metric_value,
    ) in validation_metrics.items():
        print(f"  {metric_name}: {metric_value}")


if __name__ == "__main__":
    main()

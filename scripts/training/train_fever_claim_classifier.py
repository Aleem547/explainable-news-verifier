import argparse
import json
import re
from pathlib import Path

import torch
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    Trainer,
    TrainingArguments,
)

from ml.classification.dataset import (
    FeverClassificationDataset,
)
from ml.classification.labels import (
    ID_TO_LABEL,
    LABEL_TO_ID,
)
from ml.classification.metrics import (
    compute_classification_metrics,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATASET_PATH = PROJECT_ROOT / "data" / "processed" / "fever" / "claim_classification.parquet"

MODEL_ROOT = PROJECT_ROOT / "models" / "claim_classifier"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

DEFAULT_MODEL = "distilbert-base-uncased"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Train a Transformer FEVER claim classification baseline.")
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
        default=128,
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
    name = model_name.split("/")[-1]

    return re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        name,
    )


def build_run_name(
    *,
    model_name: str,
    max_train_examples: int | None,
) -> str:
    model_component = safe_model_name(model_name)

    if max_train_examples is None:
        dataset_component = "full"
    else:
        if max_train_examples % 1000 == 0:
            dataset_component = f"{max_train_examples // 1000}k"
        else:
            dataset_component = str(max_train_examples)

    return f"{model_component}_fever_balanced_{dataset_component}"


def main() -> None:
    arguments = parse_arguments()

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

    tokenizer = AutoTokenizer.from_pretrained(arguments.model)

    print("Loading training dataset...")

    train_dataset = FeverClassificationDataset(
        parquet_path=DATASET_PATH,
        split="train",
        tokenizer=tokenizer,
        max_length=(arguments.max_length),
        max_examples=(arguments.max_train_examples),
        balanced=(arguments.max_train_examples is not None),
        seed=42,
    )

    print("Loading validation dataset...")

    validation_dataset = FeverClassificationDataset(
        parquet_path=DATASET_PATH,
        split="validation",
        tokenizer=tokenizer,
        max_length=(arguments.max_length),
        max_examples=(arguments.max_validation_examples),
        balanced=(arguments.max_validation_examples is not None),
        seed=43,
    )

    print()

    print(f"Training examples: {len(train_dataset):,}")

    print(f"Validation examples: {len(validation_dataset):,}")

    id2label = {label_id: label.value for label_id, label in ID_TO_LABEL.items()}

    label2id = {label.value: label_id for label, label_id in LABEL_TO_ID.items()}

    print()
    print(f"Loading model: {arguments.model}")

    model = AutoModelForSequenceClassification.from_pretrained(
        arguments.model,
        num_labels=3,
        id2label=id2label,
        label2id=label2id,
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
        data_collator=data_collator,
        compute_metrics=(compute_classification_metrics),
    )

    print()
    print("Starting Transformer training...")

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
        "stage": ("claim_classifier_model_comparison"),
        "run_name": run_name,
        "model": arguments.model,
        "device": ("cuda" if torch.cuda.is_available() else "cpu"),
        "epochs": (arguments.epochs),
        "batch_size": (arguments.batch_size),
        "learning_rate": (arguments.learning_rate),
        "max_length": (arguments.max_length),
        "balanced_train_subset": (arguments.max_train_examples is not None),
        "balanced_validation_subset": (arguments.max_validation_examples is not None),
        "training_examples": len(train_dataset),
        "validation_examples": len(validation_dataset),
        "max_train_examples": (arguments.max_train_examples),
        "max_validation_examples": (arguments.max_validation_examples),
        "train_metrics": (train_result.metrics),
        "validation_metrics": (validation_metrics),
        "label_mapping": {label.value: label_id for label, label_id in LABEL_TO_ID.items()},
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
    print("Claim classifier training complete.")

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

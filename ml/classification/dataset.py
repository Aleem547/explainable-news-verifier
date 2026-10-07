from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
from torch.utils.data import Dataset
from transformers import PreTrainedTokenizerBase


@dataclass(frozen=True)
class ClassificationExample:
    claim_id: int
    claim: str
    label_id: int


class FeverClassificationDataset(Dataset[dict[str, Any]]):
    def __init__(
        self,
        *,
        parquet_path: Path,
        split: str,
        tokenizer: PreTrainedTokenizerBase,
        max_length: int = 128,
        max_examples: int | None = None,
        balanced: bool = False,
        seed: int = 42,
    ) -> None:
        if not parquet_path.exists():
            raise FileNotFoundError(f"Classification dataset not found: {parquet_path}")

        if max_length <= 0:
            raise ValueError("max_length must be greater than zero.")

        frame = (
            pl.scan_parquet(parquet_path)
            .filter(pl.col("split") == split)
            .select(
                [
                    "claim_id",
                    "claim",
                    "label_id",
                ]
            )
            .collect()
        )

        if frame.is_empty():
            raise ValueError(f"No classification rows found for split: {split}")

        if balanced:
            if max_examples is None:
                raise ValueError("Balanced sampling requires max_examples.")

            if max_examples < 3:
                raise ValueError("Balanced sampling requires at least 3 examples.")

            examples_per_label = max_examples // 3

            sampled_frames: list[pl.DataFrame] = []

            for label_id in (
                0,
                1,
                2,
            ):
                label_frame = frame.filter(pl.col("label_id") == label_id)

                sample_size = min(
                    examples_per_label,
                    label_frame.height,
                )

                sampled_frames.append(
                    label_frame.sample(
                        n=sample_size,
                        shuffle=True,
                        seed=(seed + label_id),
                    )
                )

            frame = pl.concat(sampled_frames).sample(
                fraction=1.0,
                shuffle=True,
                seed=seed,
            )

        elif max_examples is not None:
            if max_examples <= 0:
                raise ValueError("max_examples must be greater than zero.")

            frame = frame.sort("claim_id").head(max_examples)

        else:
            frame = frame.sort("claim_id")

        self.examples = [
            ClassificationExample(
                claim_id=int(row["claim_id"]),
                claim=str(row["claim"]),
                label_id=int(row["label_id"]),
            )
            for row in frame.iter_rows(named=True)
        ]

        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(
        self,
        index: int,
    ) -> dict[str, Any]:
        example = self.examples[index]

        tokenizer_output = self.tokenizer(
            example.claim,
            truncation=True,
            max_length=(self.max_length),
        )

        encoded: dict[
            str,
            Any,
        ] = dict(tokenizer_output)

        encoded["labels"] = example.label_id

        return encoded

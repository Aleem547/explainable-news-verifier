from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
from torch.utils.data import Dataset
from transformers import PreTrainedTokenizerBase


@dataclass(frozen=True)
class NliExample:
    example_id: int
    premise: str
    claim: str
    label_id: int


class FeverNliDataset(Dataset[dict[str, Any]]):
    def __init__(
        self,
        *,
        parquet_path: Path,
        split: str,
        tokenizer: PreTrainedTokenizerBase,
        max_length: int = 256,
        max_examples: int | None = None,
        balanced: bool = False,
        seed: int = 42,
    ) -> None:
        if not parquet_path.exists():
            raise FileNotFoundError(f"NLI dataset not found: {parquet_path}")

        if max_length <= 0:
            raise ValueError("max_length must be greater than zero.")

        frame = (
            pl.scan_parquet(parquet_path)
            .filter(pl.col("split") == split)
            .select(
                [
                    "example_id",
                    "premise",
                    "claim",
                    "nli_label_id",
                ]
            )
            .collect()
        )

        if frame.is_empty():
            raise ValueError(f"No NLI rows found for split: {split}")

        if balanced:
            if max_examples is None:
                raise ValueError("Balanced sampling requires max_examples.")

            if max_examples < 3:
                raise ValueError("Balanced sampling requires at least three examples.")

            per_label = max_examples // 3

            sampled_frames: list[pl.DataFrame] = []

            for label_id in (
                0,
                1,
                2,
            ):
                label_frame = frame.filter(pl.col("nli_label_id") == label_id)

                sample_size = min(
                    per_label,
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

            frame = frame.sort("example_id").head(max_examples)

        else:
            frame = frame.sort("example_id")

        self.examples = [
            NliExample(
                example_id=int(row["example_id"]),
                premise=str(row["premise"]),
                claim=str(row["claim"]),
                label_id=int(row["nli_label_id"]),
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

        encoded_output = self.tokenizer(
            example.premise,
            example.claim,
            truncation=True,
            max_length=(self.max_length),
        )

        encoded: dict[
            str,
            Any,
        ] = dict(encoded_output)

        encoded["labels"] = example.label_id

        return encoded

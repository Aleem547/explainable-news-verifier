import argparse
import json
from pathlib import Path
from time import perf_counter

import duckdb
import numpy as np
import pyarrow.parquet as pq
from sentence_transformers import SentenceTransformer

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

CANDIDATES_PATH = PROCESSED_DIRECTORY / "sentence_candidates.parquet"

CATALOG_PATH = PROCESSED_DIRECTORY / "dense_sentence_catalog.parquet"

EMBEDDINGS_PATH = PROCESSED_DIRECTORY / "dense_sentence_embeddings.npy"

MAPPED_CANDIDATES_PATH = PROCESSED_DIRECTORY / "dense_sentence_candidates.parquet"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_dense_sentence_cache_manifest.json"

DEFAULT_MODEL_NAME = "BAAI/bge-small-en-v1.5"

DEFAULT_BATCH_SIZE = 64


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Build a persistent BGE embedding cache for FEVER candidate sentences.")
    )

    parser.add_argument(
        "--split",
        type=str,
        default="validation",
    )

    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL_NAME,
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
    )

    parser.add_argument(
        "--device",
        type=str,
        default=None,
    )

    parser.add_argument(
        "--max-sentences",
        type=int,
        default=None,
    )

    return parser.parse_args()


def sql_path(path: Path) -> str:
    return path.as_posix().replace(
        "'",
        "''",
    )


def sql_string(value: str) -> str:
    return value.replace(
        "'",
        "''",
    )


def scalar_int(
    connection: duckdb.DuckDBPyConnection,
    query: str,
) -> int:
    result = connection.execute(query).fetchone()

    if result is None:
        return 0

    return int(result[0])


def remove_old_outputs() -> None:
    for path in (
        CATALOG_PATH,
        EMBEDDINGS_PATH,
        MAPPED_CANDIDATES_PATH,
    ):
        if path.exists():
            path.unlink()


def build_catalog(
    *,
    split: str,
    max_sentences: int | None,
) -> tuple[int, int]:
    candidates_sql = sql_path(CANDIDATES_PATH)

    catalog_sql = sql_path(CATALOG_PATH)

    split_sql = sql_string(split)

    connection = duckdb.connect()

    try:
        source_rows = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{candidates_sql}'
            )
            WHERE split = '{split_sql}'
            """,
        )

        limit_clause = ""

        if max_sentences is not None:
            if max_sentences <= 0:
                raise ValueError("max_sentences must be greater than zero.")

            limit_clause = f"LIMIT {max_sentences}"

        print("Building unique sentence catalog...")

        connection.execute(
            f"""
            COPY (
                SELECT
                    ROW_NUMBER() OVER (
                        ORDER BY
                            page_id,
                            sentence_id
                    ) - 1 AS embedding_row,

                    page_id,
                    sentence_id,
                    sentence_text

                FROM (
                    SELECT
                        page_id,
                        sentence_id,
                        MAX(
                            sentence_text
                        ) AS sentence_text

                    FROM read_parquet(
                        '{candidates_sql}'
                    )

                    WHERE split = '{split_sql}'

                      AND sentence_text
                        IS NOT NULL

                      AND TRIM(
                            sentence_text
                          ) <> ''

                    GROUP BY
                        page_id,
                        sentence_id

                    ORDER BY
                        page_id,
                        sentence_id

                    {limit_clause}
                )
            )
            TO '{catalog_sql}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD
            )
            """
        )

        unique_sentences = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{catalog_sql}'
            )
            """,
        )

    finally:
        connection.close()

    return (
        source_rows,
        unique_sentences,
    )


def build_embeddings(
    *,
    model_name: str,
    device: str | None,
    batch_size: int,
    unique_sentences: int,
) -> tuple[int, str, float]:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")

    print()
    print(f"Loading embedding model: {model_name}")

    model = SentenceTransformer(
        model_name,
        device=device,
    )

    embedding_dimension = model.get_sentence_embedding_dimension()

    if embedding_dimension is None:
        raise ValueError("Could not determine model embedding dimension.")

    model_device = str(model.device)

    print(f"Device: {model_device}")

    print(f"Embedding dimension: {embedding_dimension}")

    print(f"Unique sentences: {unique_sentences:,}")

    print(f"Batch size: {batch_size}")

    embeddings = np.lib.format.open_memmap(
        EMBEDDINGS_PATH,
        mode="w+",
        dtype=np.float32,
        shape=(
            unique_sentences,
            embedding_dimension,
        ),
    )

    parquet_file = pq.ParquetFile(CATALOG_PATH)

    processed = 0

    started = perf_counter()

    for batch in parquet_file.iter_batches(
        batch_size=batch_size,
        columns=[
            "sentence_text",
        ],
    ):
        texts = [str(value) for value in batch.column("sentence_text").to_pylist()]

        encoded = model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        encoded_array = np.asarray(
            encoded,
            dtype=np.float32,
        )

        end = processed + encoded_array.shape[0]

        embeddings[processed:end] = encoded_array

        processed = end

        if processed % 10_000 == 0 or processed == unique_sentences:
            elapsed = perf_counter() - started

            percentage = processed / unique_sentences * 100 if unique_sentences else 0.0

            print(
                f"Embedded "
                f"{processed:,} / "
                f"{unique_sentences:,} "
                f"sentences "
                f"({percentage:.2f}%) "
                f"in {elapsed:.1f}s"
            )

    embeddings.flush()

    elapsed_seconds = perf_counter() - started

    return (
        embedding_dimension,
        model_device,
        elapsed_seconds,
    )


def build_candidate_mapping(
    *,
    split: str,
) -> int:
    candidates_sql = sql_path(CANDIDATES_PATH)

    catalog_sql = sql_path(CATALOG_PATH)

    output_sql = sql_path(MAPPED_CANDIDATES_PATH)

    split_sql = sql_string(split)

    connection = duckdb.connect()

    try:
        print()
        print("Mapping claim candidates to cached embeddings...")

        connection.execute(
            f"""
            COPY (
                SELECT
                    c.claim_id,
                    c.split,
                    c.label,
                    c.claim,

                    c.page_rank,
                    c.page_id,
                    c.page_title,
                    c.page_score,

                    c.sentence_id,
                    c.sentence_text,

                    d.embedding_row

                FROM read_parquet(
                    '{candidates_sql}'
                ) AS c

                INNER JOIN read_parquet(
                    '{catalog_sql}'
                ) AS d

                    ON c.page_id =
                        d.page_id

                    AND c.sentence_id =
                        d.sentence_id

                WHERE c.split =
                    '{split_sql}'

                ORDER BY
                    c.claim_id,
                    c.page_rank,
                    c.sentence_id
            )
            TO '{output_sql}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD
            )
            """
        )

        mapped_rows = scalar_int(
            connection,
            f"""
            SELECT COUNT(*)
            FROM read_parquet(
                '{output_sql}'
            )
            """,
        )

    finally:
        connection.close()

    return mapped_rows


def build_cache(
    *,
    split: str,
    model_name: str,
    device: str | None,
    batch_size: int,
    max_sentences: int | None,
) -> dict[str, object]:
    if not CANDIDATES_PATH.exists():
        raise FileNotFoundError(f"Missing sentence candidates: {CANDIDATES_PATH}")

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    remove_old_outputs()

    source_rows, unique_sentences = build_catalog(
        split=split,
        max_sentences=max_sentences,
    )

    if unique_sentences == 0:
        raise ValueError("No sentences found for dense embedding cache.")

    print(f"Candidate rows: {source_rows:,}")

    print(f"Unique sentences: {unique_sentences:,}")

    (
        embedding_dimension,
        model_device,
        embedding_seconds,
    ) = build_embeddings(
        model_name=model_name,
        device=device,
        batch_size=batch_size,
        unique_sentences=unique_sentences,
    )

    mapped_rows = build_candidate_mapping(
        split=split,
    )

    embedding_size_bytes = EMBEDDINGS_PATH.stat().st_size

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": "dense_sentence_cache",
        "split": split,
        "model": model_name,
        "device": model_device,
        "batch_size": batch_size,
        "embedding_dimension": (embedding_dimension),
        "candidate_rows": source_rows,
        "unique_sentences": (unique_sentences),
        "mapped_candidate_rows": (mapped_rows),
        "embedding_seconds": (embedding_seconds),
        "max_sentences": (max_sentences),
        "artifacts": {
            "catalog": str(CATALOG_PATH.relative_to(PROJECT_ROOT)),
            "embeddings": str(EMBEDDINGS_PATH.relative_to(PROJECT_ROOT)),
            "mapped_candidates": str(MAPPED_CANDIDATES_PATH.relative_to(PROJECT_ROOT)),
            "embedding_file_size_bytes": (embedding_size_bytes),
        },
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
    print("Dense sentence cache completed.")

    print(f"Unique sentences: {unique_sentences:,}")

    print(f"Embedding dimension: {embedding_dimension}")

    print(f"Mapped candidate rows: {mapped_rows:,}")

    print(f"Embedding file size: {embedding_size_bytes / 1_000_000:.2f} MB")

    print(f"Embedding time: {embedding_seconds:.2f} seconds")

    print(f"Manifest: {MANIFEST_PATH}")

    return manifest


def main() -> None:
    arguments = parse_arguments()

    build_cache(
        split=arguments.split,
        model_name=arguments.model,
        device=arguments.device,
        batch_size=arguments.batch_size,
        max_sentences=(arguments.max_sentences),
    )


if __name__ == "__main__":
    main()

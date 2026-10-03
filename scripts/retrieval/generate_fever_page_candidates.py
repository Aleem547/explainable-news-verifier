import argparse
import json
from pathlib import Path
from time import perf_counter

import polars as pl

from ml.retrieval.sparse.tantivy_page_retriever import (
    TantivyPageRetriever,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

INDEX_DIRECTORY = PROJECT_ROOT / "data" / "indexes" / "fever" / "page_bm25"

QUERIES_PATH = PROCESSED_DIRECTORY / "retrieval_queries.parquet"

OUTPUT_PATH = PROCESSED_DIRECTORY / "bm25_page_candidates.parquet"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_bm25_page_candidates_manifest.json"

DEFAULT_TOP_K = 20


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Generate BM25 Wikipedia page candidates for FEVER claims.")
    )

    parser.add_argument(
        "--split",
        type=str,
        default="validation",
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
    )

    parser.add_argument(
        "--max-queries",
        type=int,
        default=None,
    )

    return parser.parse_args()


def load_queries(
    split: str,
    max_queries: int | None,
) -> pl.DataFrame:
    query = (
        pl.scan_parquet(QUERIES_PATH)
        .filter(pl.col("split") == split)
        .select(
            [
                "claim_id",
                "split",
                "claim",
                "label",
            ]
        )
        .sort("claim_id")
    )

    if max_queries is not None:
        query = query.head(max_queries)

    return query.collect()


def generate_candidates(
    split: str,
    top_k: int,
    max_queries: int | None,
) -> dict[str, object]:
    if not QUERIES_PATH.exists():
        raise FileNotFoundError(f"Missing retrieval queries file: {QUERIES_PATH}")

    if not INDEX_DIRECTORY.exists():
        raise FileNotFoundError(f"Missing Tantivy page index: {INDEX_DIRECTORY}")

    if top_k <= 0:
        raise ValueError("top_k must be greater than zero.")

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    queries = load_queries(
        split,
        max_queries,
    )

    if queries.is_empty():
        raise ValueError(f"No queries found for split: {split}")

    print("Generating FEVER BM25 page candidates...")

    print(f"Split: {split}")

    print(f"Queries: {queries.height:,}")

    print(f"Top-K pages: {top_k}")

    retriever = TantivyPageRetriever(INDEX_DIRECTORY)

    rows: list[dict[str, object]] = []

    started = perf_counter()

    for index, row in enumerate(
        queries.iter_rows(named=True),
        start=1,
    ):
        claim_id = int(row["claim_id"])

        claim = str(row["claim"])

        label = str(row["label"])

        results = retriever.search(
            claim,
            limit=top_k,
        )

        for result in results:
            rows.append(
                {
                    "claim_id": claim_id,
                    "split": split,
                    "label": label,
                    "claim": claim,
                    "page_rank": result.rank,
                    "page_id": result.page_id,
                    "page_title": result.title,
                    "page_score": result.score,
                }
            )

        if index % 100 == 0:
            print(f"Processed {index:,} / {queries.height:,} claims")

    if not rows:
        raise ValueError("No page candidates were generated.")

    result_frame = pl.DataFrame(rows)

    result_frame.write_parquet(
        OUTPUT_PATH,
        compression="zstd",
    )

    elapsed_seconds = perf_counter() - started

    unique_claims = result_frame.select(pl.col("claim_id").n_unique()).item()

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": "bm25_page_candidates",
        "split": split,
        "top_k": top_k,
        "query_count": int(unique_claims),
        "candidate_rows": (result_frame.height),
        "elapsed_seconds": (elapsed_seconds),
        "output": str(OUTPUT_PATH.relative_to(PROJECT_ROOT)),
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
    print("BM25 page candidate generation complete.")

    print(f"Queries processed: {unique_claims:,}")

    print(f"Candidate rows: {result_frame.height:,}")

    print(f"Elapsed: {elapsed_seconds:.2f} seconds")

    print(f"Output: {OUTPUT_PATH}")

    return manifest


def main() -> None:
    arguments = parse_arguments()

    generate_candidates(
        split=arguments.split,
        top_k=arguments.top_k,
        max_queries=(arguments.max_queries),
    )


if __name__ == "__main__":
    main()

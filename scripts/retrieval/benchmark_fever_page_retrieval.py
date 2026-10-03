import argparse
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

import polars as pl

from ml.retrieval.evaluation import (
    first_relevant_rank,
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
)
from ml.retrieval.sparse.tantivy_page_retriever import (
    TantivyPageRetriever,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"

INDEX_DIRECTORY = PROJECT_ROOT / "data" / "indexes" / "fever" / "page_bm25"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

QUERIES_PATH = PROCESSED_DIRECTORY / "retrieval_queries.parquet"

GOLD_PAGES_PATH = PROCESSED_DIRECTORY / "retrieval_gold_pages.parquet"

RESULTS_PATH = PROCESSED_DIRECTORY / "bm25_page_retrieval_results.parquet"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_bm25_page_retrieval_manifest.json"

TOP_K_VALUES = (
    1,
    5,
    10,
    20,
    50,
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=("Benchmark FEVER BM25 Wikipedia page retrieval."))

    parser.add_argument(
        "--split",
        type=str,
        default="paper_dev",
    )

    parser.add_argument(
        "--max-queries",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=50,
    )

    return parser.parse_args()


def load_gold_pages(
    split: str,
) -> dict[int, set[str]]:
    frame = (
        pl.scan_parquet(GOLD_PAGES_PATH)
        .filter(pl.col("split") == split)
        .select(
            [
                "claim_id",
                "wiki_page",
            ]
        )
        .collect()
    )

    gold_pages: dict[
        int,
        set[str],
    ] = {}

    for row in frame.iter_rows(named=True):
        claim_id = int(row["claim_id"])

        page_id = str(row["wiki_page"])

        gold_pages.setdefault(
            claim_id,
            set(),
        ).add(page_id)

    return gold_pages


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
                "claim",
                "label",
            ]
        )
        .sort("claim_id")
    )

    if max_queries is not None:
        query = query.head(max_queries)

    return query.collect()


def benchmark(
    split: str,
    max_queries: int | None,
    limit: int,
) -> dict[str, object]:
    if limit < max(TOP_K_VALUES):
        raise ValueError(f"Search limit must be at least {max(TOP_K_VALUES)}.")

    if not QUERIES_PATH.exists():
        raise FileNotFoundError(f"Missing retrieval queries: {QUERIES_PATH}")

    if not GOLD_PAGES_PATH.exists():
        raise FileNotFoundError(f"Missing gold page data: {GOLD_PAGES_PATH}")

    print("Loading FEVER retrieval benchmark...")

    queries = load_queries(
        split,
        max_queries,
    )

    gold_pages_by_claim = load_gold_pages(split)

    print(f"Split: {split}")

    print(f"Queries: {queries.height:,}")

    print(f"Search depth: {limit}")

    retriever = TantivyPageRetriever(INDEX_DIRECTORY)

    result_rows: list[dict[str, object]] = []

    start_time = perf_counter()

    evaluated_queries = 0

    for row in queries.iter_rows(named=True):
        claim_id = int(row["claim_id"])

        claim = str(row["claim"])

        label = str(row["label"])

        gold_pages = gold_pages_by_claim.get(claim_id)

        if not gold_pages:
            continue

        search_start = perf_counter()

        results = retriever.search(
            claim,
            limit=limit,
        )

        latency_ms = (perf_counter() - search_start) * 1000

        retrieved_pages = [result.page_id for result in results]

        first_rank = first_relevant_rank(
            retrieved_pages,
            gold_pages,
        )

        result_rows.append(
            {
                "claim_id": claim_id,
                "split": split,
                "label": label,
                "claim": claim,
                "gold_page_count": (len(gold_pages)),
                "first_relevant_rank": (first_rank),
                "hit_at_1": hit_at_k(
                    retrieved_pages,
                    gold_pages,
                    1,
                ),
                "hit_at_5": hit_at_k(
                    retrieved_pages,
                    gold_pages,
                    5,
                ),
                "hit_at_10": hit_at_k(
                    retrieved_pages,
                    gold_pages,
                    10,
                ),
                "hit_at_20": hit_at_k(
                    retrieved_pages,
                    gold_pages,
                    20,
                ),
                "hit_at_50": hit_at_k(
                    retrieved_pages,
                    gold_pages,
                    50,
                ),
                "recall_at_1": (
                    recall_at_k(
                        retrieved_pages,
                        gold_pages,
                        1,
                    )
                ),
                "recall_at_5": (
                    recall_at_k(
                        retrieved_pages,
                        gold_pages,
                        5,
                    )
                ),
                "recall_at_10": (
                    recall_at_k(
                        retrieved_pages,
                        gold_pages,
                        10,
                    )
                ),
                "recall_at_20": (
                    recall_at_k(
                        retrieved_pages,
                        gold_pages,
                        20,
                    )
                ),
                "recall_at_50": (
                    recall_at_k(
                        retrieved_pages,
                        gold_pages,
                        50,
                    )
                ),
                "reciprocal_rank": (
                    reciprocal_rank(
                        retrieved_pages,
                        gold_pages,
                    )
                ),
                "latency_ms": (latency_ms),
            }
        )

        evaluated_queries += 1

        if evaluated_queries % 100 == 0:
            print(f"Evaluated {evaluated_queries:,} / {queries.height:,}")

    if not result_rows:
        raise ValueError("No benchmark queries were evaluated.")

    result_frame = pl.DataFrame(result_rows)

    result_frame.write_parquet(
        RESULTS_PATH,
        compression="zstd",
    )

    elapsed_seconds = perf_counter() - start_time

    metrics: dict[str, float] = {}

    for k in TOP_K_VALUES:
        metrics[f"hit_at_{k}"] = mean(
            float(value) for value in result_frame[f"hit_at_{k}"].to_list()
        )

        metrics[f"mean_recall_at_{k}"] = mean(
            float(value) for value in result_frame[f"recall_at_{k}"].to_list()
        )

    metrics["mrr"] = mean(float(value) for value in result_frame["reciprocal_rank"].to_list())

    metrics["mean_latency_ms"] = mean(
        float(value) for value in result_frame["latency_ms"].to_list()
    )

    metrics["queries_per_second"] = evaluated_queries / elapsed_seconds

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": ("bm25_page_retrieval_benchmark"),
        "split": split,
        "evaluated_queries": (evaluated_queries),
        "search_limit": limit,
        "metrics": metrics,
        "elapsed_seconds": (elapsed_seconds),
        "results_path": str(RESULTS_PATH.relative_to(PROJECT_ROOT)),
    }

    MANIFEST_PATH.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return manifest


def main() -> None:
    arguments = parse_arguments()

    manifest = benchmark(
        split=arguments.split,
        max_queries=(arguments.max_queries),
        limit=arguments.limit,
    )

    metrics = manifest["metrics"]

    if not isinstance(
        metrics,
        dict,
    ):
        raise TypeError("Benchmark metrics are invalid.")

    print()
    print("FEVER BM25 page retrieval benchmark complete.")

    print()

    for k in TOP_K_VALUES:
        hit = float(metrics[f"hit_at_{k}"])

        recall = float(metrics[f"mean_recall_at_{k}"])

        print(f"Hit@{k}: {hit:.4%}")

        print(f"Mean Recall@{k}: {recall:.4%}")

    print()

    print(f"MRR: {float(metrics['mrr']):.4f}")

    print(f"Mean latency: {float(metrics['mean_latency_ms']):.2f} ms")

    print(f"Queries/sec: {float(metrics['queries_per_second']):.2f}")

    print()

    print(f"Results: {RESULTS_PATH}")

    print(f"Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()

import argparse
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

import numpy as np
import polars as pl
from sentence_transformers import SentenceTransformer

from ml.retrieval.dense.bge_sentence_ranker import (
    DEFAULT_MODEL_NAME,
    prepare_query,
)
from ml.retrieval.evaluation import (
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

CANDIDATES_PATH = PROCESSED_DIRECTORY / "dense_sentence_candidates.parquet"

EMBEDDINGS_PATH = PROCESSED_DIRECTORY / "dense_sentence_embeddings.npy"

QRELS_PATH = PROCESSED_DIRECTORY / "retrieval_qrels.parquet"

RESULTS_PATH = PROCESSED_DIRECTORY / "dense_sentence_retrieval_results.parquet"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_dense_sentence_retrieval_manifest.json"

TOP_K_VALUES = (
    1,
    5,
    10,
    20,
    50,
)

SentenceKey = tuple[str, int]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Benchmark BGE dense sentence retrieval on FEVER.")
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
        default=32,
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


def load_gold_sentences(
    split: str,
) -> dict[int, set[SentenceKey]]:
    frame = (
        pl.scan_parquet(QRELS_PATH)
        .filter(pl.col("split") == split)
        .select(
            [
                "claim_id",
                "wiki_page",
                "sentence_id",
            ]
        )
        .collect()
    )

    gold: dict[
        int,
        set[SentenceKey],
    ] = {}

    for row in frame.iter_rows(named=True):
        claim_id = int(row["claim_id"])

        page_id = str(row["wiki_page"])

        sentence_id = int(row["sentence_id"])

        gold.setdefault(
            claim_id,
            set(),
        ).add(
            (
                page_id,
                sentence_id,
            )
        )

    return gold


def load_candidates(
    split: str,
    max_queries: int | None,
) -> pl.DataFrame:
    frame = (
        pl.scan_parquet(CANDIDATES_PATH)
        .filter(pl.col("split") == split)
        .select(
            [
                "claim_id",
                "claim",
                "page_id",
                "sentence_id",
                "embedding_row",
            ]
        )
        .sort(
            [
                "claim_id",
                "page_id",
                "sentence_id",
            ]
        )
        .collect()
    )

    if max_queries is None:
        return frame

    claim_ids = frame.select("claim_id").unique(maintain_order=True).head(max_queries)

    return frame.join(
        claim_ids,
        on="claim_id",
        how="inner",
    )


def benchmark(
    *,
    split: str,
    model_name: str,
    batch_size: int,
    max_queries: int | None,
    limit: int,
) -> dict[str, object]:
    if limit < max(TOP_K_VALUES):
        raise ValueError(f"limit must be at least {max(TOP_K_VALUES)}.")

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")

    if not CANDIDATES_PATH.exists():
        raise FileNotFoundError(f"Missing dense candidates: {CANDIDATES_PATH}")

    if not EMBEDDINGS_PATH.exists():
        raise FileNotFoundError(f"Missing dense embeddings: {EMBEDDINGS_PATH}")

    if not QRELS_PATH.exists():
        raise FileNotFoundError(f"Missing qrels: {QRELS_PATH}")

    print("Loading dense retrieval data...")

    candidates = load_candidates(
        split,
        max_queries,
    )

    gold_by_claim = load_gold_sentences(split)

    grouped = candidates.partition_by(
        "claim_id",
        maintain_order=True,
    )

    print(f"Split: {split}")

    print(f"Queries: {len(grouped):,}")

    print(f"Candidate rows: {candidates.height:,}")

    embeddings = np.load(
        EMBEDDINGS_PATH,
        mmap_mode="r",
    )

    print(f"Embedding matrix: {embeddings.shape}")

    print(f"Loading model: {model_name}")

    model = SentenceTransformer(
        model_name,
        device="cpu",
    )

    result_rows: list[dict[str, object]] = []

    started = perf_counter()

    evaluated = 0

    for group in grouped:
        claim_id = int(group["claim_id"][0])

        gold_sentences = gold_by_claim.get(claim_id)

        if not gold_sentences:
            continue

        claim = str(group["claim"][0])

        prepared_query = prepare_query(claim)

        if not prepared_query:
            continue

        query_started = perf_counter()

        query_embedding = model.encode(
            [prepared_query],
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]

        embedding_rows = np.asarray(
            group["embedding_row"].to_list(),
            dtype=np.int64,
        )

        candidate_embeddings = embeddings[embedding_rows]

        scores = candidate_embeddings @ query_embedding

        result_limit = min(
            limit,
            len(scores),
        )

        if result_limit == 0:
            continue

        if result_limit == len(scores):
            ranked_indices = np.argsort(-scores)
        else:
            top_indices = np.argpartition(
                -scores,
                result_limit - 1,
            )[:result_limit]

            ranked_indices = top_indices[np.argsort(-scores[top_indices])]

        ranked_indices = ranked_indices[:result_limit]

        page_ids = group["page_id"].to_list()

        sentence_ids = group["sentence_id"].to_list()

        retrieved = [
            (
                str(page_ids[index]),
                int(sentence_ids[index]),
            )
            for index in ranked_indices
        ]

        serialized_retrieved = [f"{page_id}::{sentence_id}" for page_id, sentence_id in retrieved]

        serialized_gold = {f"{page_id}::{sentence_id}" for page_id, sentence_id in gold_sentences}

        latency_ms = (perf_counter() - query_started) * 1000

        row: dict[str, object] = {
            "claim_id": claim_id,
            "claim": claim,
            "candidate_count": (group.height),
            "gold_sentence_count": (len(gold_sentences)),
            "latency_ms": latency_ms,
        }

        for k in TOP_K_VALUES:
            row[f"hit_at_{k}"] = hit_at_k(
                serialized_retrieved,
                serialized_gold,
                k,
            )

            row[f"recall_at_{k}"] = recall_at_k(
                serialized_retrieved,
                serialized_gold,
                k,
            )

        row["reciprocal_rank"] = reciprocal_rank(
            serialized_retrieved,
            serialized_gold,
        )

        result_rows.append(row)

        evaluated += 1

        if evaluated % 100 == 0:
            print(f"Evaluated {evaluated:,} / {len(grouped):,}")

    if not result_rows:
        raise ValueError("No dense retrieval queries were evaluated.")

    result_frame = pl.DataFrame(result_rows)

    result_frame.write_parquet(
        RESULTS_PATH,
        compression="zstd",
    )

    elapsed_seconds = perf_counter() - started

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

    metrics["queries_per_second"] = evaluated / elapsed_seconds

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": ("dense_sentence_retrieval_benchmark"),
        "model": model_name,
        "split": split,
        "evaluated_queries": evaluated,
        "search_limit": limit,
        "elapsed_seconds": (elapsed_seconds),
        "metrics": metrics,
        "results": str(RESULTS_PATH.relative_to(PROJECT_ROOT)),
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
        model_name=arguments.model,
        batch_size=arguments.batch_size,
        max_queries=(arguments.max_queries),
        limit=arguments.limit,
    )

    metrics_object = manifest["metrics"]

    if not isinstance(
        metrics_object,
        dict,
    ):
        raise TypeError("Invalid metrics.")

    metrics = metrics_object

    print()
    print("FEVER dense sentence retrieval benchmark complete.")

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

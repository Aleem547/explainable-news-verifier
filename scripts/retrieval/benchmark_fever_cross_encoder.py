import argparse
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

import polars as pl

from ml.retrieval.evaluation import (
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
)
from ml.retrieval.rerank.cross_encoder import (
    DEFAULT_CROSS_ENCODER_MODEL,
    CrossEncoderSentenceReranker,
)
from ml.retrieval.sparse.bm25_sentence_ranker import (
    SentenceDocument,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

HYBRID_RANKINGS_PATH = PROCESSED_DIRECTORY / "hybrid_sentence_rankings.parquet"

CANDIDATES_PATH = PROCESSED_DIRECTORY / "dense_sentence_candidates.parquet"

QRELS_PATH = PROCESSED_DIRECTORY / "retrieval_qrels.parquet"

RESULTS_PATH = PROCESSED_DIRECTORY / "cross_encoder_retrieval_results.parquet"

RANKINGS_PATH = PROCESSED_DIRECTORY / "cross_encoder_sentence_rankings.parquet"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_cross_encoder_retrieval_manifest.json"

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
        description=("Benchmark CrossEncoder reranking over FEVER hybrid candidates.")
    )

    parser.add_argument(
        "--split",
        type=str,
        default="validation",
    )

    parser.add_argument(
        "--model",
        type=str,
        default=(DEFAULT_CROSS_ENCODER_MODEL),
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
    )

    parser.add_argument(
        "--source-depth",
        type=int,
        default=50,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=50,
    )

    parser.add_argument(
        "--max-queries",
        type=int,
        default=None,
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

        key = (
            str(row["wiki_page"]),
            int(row["sentence_id"]),
        )

        gold.setdefault(
            claim_id,
            set(),
        ).add(key)

    return gold


def load_candidates(
    *,
    split: str,
    source_depth: int,
    max_queries: int | None,
) -> pl.DataFrame:
    rankings = (
        pl.scan_parquet(HYBRID_RANKINGS_PATH)
        .filter(pl.col("rank") <= source_depth)
        .select(
            [
                "claim_id",
                "rank",
                "page_id",
                "sentence_id",
                "rrf_score",
            ]
        )
    )

    candidate_text = (
        pl.scan_parquet(CANDIDATES_PATH)
        .filter(pl.col("split") == split)
        .select(
            [
                "claim_id",
                "claim",
                "page_id",
                "sentence_id",
                "sentence_text",
            ]
        )
        .unique(
            subset=[
                "claim_id",
                "page_id",
                "sentence_id",
            ],
            keep="first",
        )
    )

    frame = (
        rankings.join(
            candidate_text,
            on=[
                "claim_id",
                "page_id",
                "sentence_id",
            ],
            how="inner",
        )
        .sort(
            [
                "claim_id",
                "rank",
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
    source_depth: int,
    limit: int,
    max_queries: int | None,
) -> dict[str, object]:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")

    if source_depth <= 0:
        raise ValueError("source_depth must be greater than zero.")

    if limit < max(TOP_K_VALUES):
        raise ValueError(f"limit must be at least {max(TOP_K_VALUES)}.")

    if source_depth < limit:
        raise ValueError("source_depth must be greater than or equal to limit.")

    for path in (
        HYBRID_RANKINGS_PATH,
        CANDIDATES_PATH,
        QRELS_PATH,
    ):
        if not path.exists():
            raise FileNotFoundError(f"Required file missing: {path}")

    print("Loading hybrid candidates...")

    candidates = load_candidates(
        split=split,
        source_depth=source_depth,
        max_queries=max_queries,
    )

    if candidates.is_empty():
        raise ValueError("No CrossEncoder candidates found.")

    groups = candidates.partition_by(
        "claim_id",
        maintain_order=True,
    )

    gold_by_claim = load_gold_sentences(split)

    print(f"Queries: {len(groups):,}")

    print(f"Candidate rows: {candidates.height:,}")

    print(f"Source depth: {source_depth}")

    print(f"Loading CrossEncoder: {model_name}")

    reranker = CrossEncoderSentenceReranker(
        model_name=model_name,
        device="cpu",
        batch_size=batch_size,
    )

    result_rows: list[dict[str, object]] = []

    ranking_rows: list[dict[str, object]] = []

    started = perf_counter()

    evaluated = 0

    for group in groups:
        claim_id = int(group["claim_id"][0])

        claim = str(group["claim"][0])

        gold_sentences = gold_by_claim.get(claim_id)

        if not gold_sentences:
            continue

        documents: list[SentenceDocument] = []

        hybrid_rank_map: dict[
            SentenceKey,
            int,
        ] = {}

        for row in group.iter_rows(named=True):
            sentence_text = str(row["sentence_text"] or "").strip()

            if not sentence_text:
                continue

            page_id = str(row["page_id"])

            sentence_id = int(row["sentence_id"])

            key = (
                page_id,
                sentence_id,
            )

            documents.append(
                SentenceDocument(
                    page_id=page_id,
                    sentence_id=sentence_id,
                    text=sentence_text,
                )
            )

            hybrid_rank_map[key] = int(row["rank"])

        if not documents:
            continue

        query_started = perf_counter()

        results = reranker.rerank(
            claim,
            documents,
            limit=limit,
        )

        latency_ms = (perf_counter() - query_started) * 1000

        retrieved = [
            (
                result.page_id,
                result.sentence_id,
            )
            for result in results
        ]

        serialized_retrieved = [f"{page_id}::{sentence_id}" for page_id, sentence_id in retrieved]

        serialized_gold = {f"{page_id}::{sentence_id}" for page_id, sentence_id in gold_sentences}

        result_row: dict[
            str,
            object,
        ] = {
            "claim_id": claim_id,
            "claim": claim,
            "candidate_count": len(documents),
            "gold_sentence_count": len(gold_sentences),
            "latency_ms": latency_ms,
        }

        for k in TOP_K_VALUES:
            result_row[f"hit_at_{k}"] = hit_at_k(
                serialized_retrieved,
                serialized_gold,
                k,
            )

            result_row[f"recall_at_{k}"] = recall_at_k(
                serialized_retrieved,
                serialized_gold,
                k,
            )

        result_row["reciprocal_rank"] = reciprocal_rank(
            serialized_retrieved,
            serialized_gold,
        )

        result_rows.append(result_row)

        for result in results:
            key = (
                result.page_id,
                result.sentence_id,
            )

            ranking_rows.append(
                {
                    "claim_id": claim_id,
                    "rank": result.rank,
                    "page_id": (result.page_id),
                    "sentence_id": (result.sentence_id),
                    "cross_encoder_score": (result.score),
                    "hybrid_rank": (hybrid_rank_map.get(key)),
                }
            )

        evaluated += 1

        if evaluated % 25 == 0:
            print(f"Evaluated {evaluated:,} / {len(groups):,}")

    if not result_rows:
        raise ValueError("No CrossEncoder queries were evaluated.")

    result_frame = pl.DataFrame(result_rows)

    ranking_frame = pl.DataFrame(ranking_rows)

    result_frame.write_parquet(
        RESULTS_PATH,
        compression="zstd",
    )

    ranking_frame.write_parquet(
        RANKINGS_PATH,
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

    metrics["mean_rerank_latency_ms"] = mean(
        float(value) for value in result_frame["latency_ms"].to_list()
    )

    metrics["queries_per_second"] = evaluated / elapsed_seconds

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": ("cross_encoder_reranking"),
        "model": model_name,
        "split": split,
        "evaluated_queries": evaluated,
        "source_depth": source_depth,
        "search_limit": limit,
        "elapsed_seconds": (elapsed_seconds),
        "metrics": metrics,
        "results": str(RESULTS_PATH.relative_to(PROJECT_ROOT)),
        "rankings": str(RANKINGS_PATH.relative_to(PROJECT_ROOT)),
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
        source_depth=(arguments.source_depth),
        limit=arguments.limit,
        max_queries=(arguments.max_queries),
    )

    metrics_object = manifest["metrics"]

    if not isinstance(
        metrics_object,
        dict,
    ):
        raise TypeError("Invalid metrics.")

    metrics = metrics_object

    print()
    print("FEVER CrossEncoder benchmark complete.")

    print()

    for k in TOP_K_VALUES:
        print(f"Hit@{k}: {float(metrics[f'hit_at_{k}']):.4%}")

        print(f"Mean Recall@{k}: {float(metrics[f'mean_recall_at_{k}']):.4%}")

    print()

    print(f"MRR: {float(metrics['mrr']):.4f}")

    print(f"Mean rerank latency: {float(metrics['mean_rerank_latency_ms']):.2f} ms")

    print(f"Queries/sec: {float(metrics['queries_per_second']):.2f}")

    print()

    print(f"Results: {RESULTS_PATH}")

    print(f"Rankings: {RANKINGS_PATH}")

    print(f"Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()

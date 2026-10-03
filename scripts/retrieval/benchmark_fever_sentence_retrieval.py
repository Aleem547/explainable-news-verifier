import argparse
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

import polars as pl
import pyarrow.parquet as pq

from ml.retrieval.evaluation import (
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
)
from ml.retrieval.sparse.bm25_sentence_ranker import (
    BM25SentenceRanker,
    SentenceDocument,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

CANDIDATES_PATH = PROCESSED_DIRECTORY / "sentence_candidates.parquet"

QRELS_PATH = PROCESSED_DIRECTORY / "retrieval_qrels.parquet"

RESULTS_PATH = PROCESSED_DIRECTORY / "bm25_sentence_retrieval_results.parquet"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_bm25_sentence_retrieval_manifest.json"

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
        description=("Benchmark BM25 sentence retrieval on FEVER candidate pages.")
    )

    parser.add_argument(
        "--split",
        type=str,
        default="validation",
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


def evaluate_claim(
    *,
    claim_id: int,
    claim: str,
    documents: list[SentenceDocument],
    gold_sentences: set[SentenceKey],
    ranker: BM25SentenceRanker,
    limit: int,
) -> dict[str, object]:
    unique_documents: dict[
        SentenceKey,
        SentenceDocument,
    ] = {}

    for document in documents:
        key = (
            document.page_id,
            document.sentence_id,
        )

        unique_documents.setdefault(
            key,
            document,
        )

    started = perf_counter()

    results = ranker.rank(
        claim,
        list(unique_documents.values()),
        limit=limit,
    )

    latency_ms = (perf_counter() - started) * 1000

    retrieved_keys = [
        (
            result.page_id,
            result.sentence_id,
        )
        for result in results
    ]

    serialized_retrieved = [f"{page_id}::{sentence_id}" for page_id, sentence_id in retrieved_keys]

    serialized_gold = {f"{page_id}::{sentence_id}" for page_id, sentence_id in gold_sentences}

    row: dict[str, object] = {
        "claim_id": claim_id,
        "claim": claim,
        "candidate_count": len(unique_documents),
        "gold_sentence_count": len(gold_sentences),
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

    return row


def benchmark(
    *,
    split: str,
    max_queries: int | None,
    limit: int,
) -> dict[str, object]:
    if limit < max(TOP_K_VALUES):
        raise ValueError(f"limit must be at least {max(TOP_K_VALUES)}.")

    if not CANDIDATES_PATH.exists():
        raise FileNotFoundError(f"Missing sentence candidates: {CANDIDATES_PATH}")

    if not QRELS_PATH.exists():
        raise FileNotFoundError(f"Missing sentence qrels: {QRELS_PATH}")

    gold_by_claim = load_gold_sentences(split)

    ranker = BM25SentenceRanker()

    parquet_file = pq.ParquetFile(CANDIDATES_PATH)

    result_rows: list[dict[str, object]] = []

    current_claim_id: int | None = None
    current_claim = ""
    current_split = ""
    current_documents: list[SentenceDocument] = []

    evaluated = 0

    started = perf_counter()

    def flush_current() -> bool:
        nonlocal evaluated
        nonlocal current_documents

        if current_claim_id is None:
            return False

        if current_split != split:
            current_documents = []
            return False

        gold_sentences = gold_by_claim.get(current_claim_id)

        if not gold_sentences:
            current_documents = []
            return False

        result_rows.append(
            evaluate_claim(
                claim_id=current_claim_id,
                claim=current_claim,
                documents=current_documents,
                gold_sentences=gold_sentences,
                ranker=ranker,
                limit=limit,
            )
        )

        evaluated += 1

        if evaluated % 100 == 0:
            print(f"Evaluated {evaluated:,} claims")

        current_documents = []

        return max_queries is not None and evaluated >= max_queries

    should_stop = False

    for batch in parquet_file.iter_batches(batch_size=20_000):
        rows = batch.to_pylist()

        for row in rows:
            claim_id = int(row["claim_id"])

            if current_claim_id is not None and claim_id != current_claim_id:
                should_stop = flush_current()

                if should_stop:
                    break

            if current_claim_id != claim_id:
                current_claim_id = claim_id

                current_claim = str(row["claim"])

                current_split = str(row["split"])

            sentence_text = str(row["sentence_text"] or "")

            if sentence_text.strip():
                current_documents.append(
                    SentenceDocument(
                        page_id=str(row["page_id"]),
                        sentence_id=int(row["sentence_id"]),
                        text=sentence_text,
                    )
                )

        if should_stop:
            break

    if not should_stop:
        flush_current()

    if not result_rows:
        raise ValueError("No sentence retrieval queries were evaluated.")

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

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": ("bm25_sentence_retrieval_benchmark"),
        "split": split,
        "evaluated_queries": (result_frame.height),
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
        max_queries=(arguments.max_queries),
        limit=arguments.limit,
    )

    metrics_object = manifest["metrics"]

    if not isinstance(
        metrics_object,
        dict,
    ):
        raise TypeError("Invalid benchmark metrics.")

    metrics = metrics_object

    print()
    print("FEVER BM25 sentence retrieval benchmark complete.")

    print()

    for k in TOP_K_VALUES:
        hit = float(metrics[f"hit_at_{k}"])

        recall = float(metrics[f"mean_recall_at_{k}"])

        print(f"Hit@{k}: {hit:.4%}")

        print(f"Mean Recall@{k}: {recall:.4%}")

    print()

    print(f"MRR: {float(metrics['mrr']):.4f}")

    print(f"Mean ranking latency: {float(metrics['mean_latency_ms']):.2f} ms")

    print()

    print(f"Results: {RESULTS_PATH}")

    print(f"Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()

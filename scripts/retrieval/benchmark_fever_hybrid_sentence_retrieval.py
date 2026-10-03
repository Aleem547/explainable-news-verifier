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
from ml.retrieval.hybrid.rrf import (
    RankedSentence,
    reciprocal_rank_fusion,
)
from ml.retrieval.sparse.bm25_sentence_ranker import (
    BM25SentenceRanker,
    SentenceDocument,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "fever"

METADATA_DIRECTORY = PROJECT_ROOT / "data" / "metadata"

CANDIDATES_PATH = PROCESSED_DIRECTORY / "dense_sentence_candidates.parquet"

EMBEDDINGS_PATH = PROCESSED_DIRECTORY / "dense_sentence_embeddings.npy"

QRELS_PATH = PROCESSED_DIRECTORY / "retrieval_qrels.parquet"

RESULTS_PATH = PROCESSED_DIRECTORY / "hybrid_sentence_retrieval_results.parquet"

RANKINGS_PATH = PROCESSED_DIRECTORY / "hybrid_sentence_rankings.parquet"

MANIFEST_PATH = METADATA_DIRECTORY / "fever_hybrid_sentence_retrieval_manifest.json"

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
        description=("Benchmark hybrid BM25 + BGE sentence retrieval using RRF.")
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
        default=64,
    )

    parser.add_argument(
        "--max-queries",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--source-depth",
        type=int,
        default=100,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=50,
    )

    parser.add_argument(
        "--rrf-k",
        type=int,
        default=60,
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
                "sentence_text",
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


def dense_ranking(
    *,
    documents: list[SentenceDocument],
    embedding_rows: np.ndarray,
    embeddings: np.ndarray,
    query_embedding: np.ndarray,
    limit: int,
) -> list[RankedSentence]:
    if not documents:
        return []

    candidate_embeddings = embeddings[embedding_rows]

    scores = candidate_embeddings @ query_embedding

    result_limit = min(
        limit,
        len(documents),
    )

    if result_limit == len(documents):
        ranked_indices = np.argsort(-scores)
    else:
        candidate_indices = np.argpartition(
            -scores,
            result_limit - 1,
        )[:result_limit]

        ranked_indices = candidate_indices[np.argsort(-scores[candidate_indices])]

    results: list[RankedSentence] = []

    for rank, index_value in enumerate(
        ranked_indices[:result_limit],
        start=1,
    ):
        index = int(index_value)

        document = documents[index]

        results.append(
            RankedSentence(
                page_id=document.page_id,
                sentence_id=(document.sentence_id),
                rank=rank,
            )
        )

    return results


def benchmark(
    *,
    split: str,
    model_name: str,
    batch_size: int,
    max_queries: int | None,
    source_depth: int,
    limit: int,
    rrf_k: int,
) -> dict[str, object]:
    if limit < max(TOP_K_VALUES):
        raise ValueError(f"limit must be at least {max(TOP_K_VALUES)}.")

    if source_depth < limit:
        raise ValueError("source_depth must be greater than or equal to limit.")

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")

    if rrf_k <= 0:
        raise ValueError("rrf_k must be greater than zero.")

    for path in (
        CANDIDATES_PATH,
        EMBEDDINGS_PATH,
        QRELS_PATH,
    ):
        if not path.exists():
            raise FileNotFoundError(f"Required file missing: {path}")

    candidates = load_candidates(
        split,
        max_queries,
    )

    if candidates.is_empty():
        raise ValueError("No candidate sentences found.")

    groups = candidates.partition_by(
        "claim_id",
        maintain_order=True,
    )

    gold_by_claim = load_gold_sentences(split)

    print("Loading cached sentence embeddings...")

    embeddings = np.load(
        EMBEDDINGS_PATH,
        mmap_mode="r",
    )

    print(f"Embedding matrix: {embeddings.shape}")

    print(f"Loading query model: {model_name}")

    model = SentenceTransformer(
        model_name,
        device="cpu",
    )

    claim_texts: list[str] = []
    claim_ids: list[int] = []

    for group in groups:
        claim_ids.append(int(group["claim_id"][0]))

        claim_texts.append(str(group["claim"][0]))

    prepared_queries = [prepare_query(claim) for claim in claim_texts]

    print(f"Encoding {len(prepared_queries):,} claims...")

    query_embeddings = np.asarray(
        model.encode(
            prepared_queries,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=True,
        ),
        dtype=np.float32,
    )

    print()
    print("Starting hybrid retrieval benchmark...")

    print(f"Queries: {len(groups):,}")

    print(f"Source depth: {source_depth}")

    print(f"Final depth: {limit}")

    print(f"RRF k: {rrf_k}")

    bm25_ranker = BM25SentenceRanker()

    result_rows: list[dict[str, object]] = []

    ranking_rows: list[dict[str, object]] = []

    started = perf_counter()

    evaluated = 0

    for group_index, group in enumerate(groups):
        claim_id = claim_ids[group_index]

        claim = claim_texts[group_index]

        gold_sentences = gold_by_claim.get(claim_id)

        if not gold_sentences:
            continue

        unique_documents: dict[
            SentenceKey,
            tuple[
                SentenceDocument,
                int,
            ],
        ] = {}

        for row in group.iter_rows(named=True):
            page_id = str(row["page_id"])

            sentence_id = int(row["sentence_id"])

            key = (
                page_id,
                sentence_id,
            )

            if key in unique_documents:
                continue

            sentence_text = str(row["sentence_text"] or "")

            if not sentence_text.strip():
                continue

            document = SentenceDocument(
                page_id=page_id,
                sentence_id=sentence_id,
                text=sentence_text,
            )

            embedding_row = int(row["embedding_row"])

            unique_documents[key] = (
                document,
                embedding_row,
            )

        documents = [value[0] for value in unique_documents.values()]

        embedding_rows = np.asarray(
            [value[1] for value in unique_documents.values()],
            dtype=np.int64,
        )

        if not documents:
            continue

        query_started = perf_counter()

        bm25_results = bm25_ranker.rank(
            claim,
            documents,
            limit=source_depth,
        )

        bm25_ranking = [
            RankedSentence(
                page_id=result.page_id,
                sentence_id=(result.sentence_id),
                rank=result.rank,
            )
            for result in bm25_results
        ]

        dense_results = dense_ranking(
            documents=documents,
            embedding_rows=embedding_rows,
            embeddings=embeddings,
            query_embedding=(query_embeddings[group_index]),
            limit=source_depth,
        )

        fused_results = reciprocal_rank_fusion(
            [
                bm25_ranking,
                dense_results,
            ],
            k=rrf_k,
            limit=limit,
        )

        latency_ms = (perf_counter() - query_started) * 1000

        bm25_rank_map = {
            (
                item.page_id,
                item.sentence_id,
            ): item.rank
            for item in bm25_ranking
        }

        dense_rank_map = {
            (
                item.page_id,
                item.sentence_id,
            ): item.rank
            for item in dense_results
        }

        retrieved_keys = [
            (
                item.page_id,
                item.sentence_id,
            )
            for item in fused_results
        ]

        serialized_retrieved = [
            f"{page_id}::{sentence_id}" for page_id, sentence_id in retrieved_keys
        ]

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

        for fused in fused_results:
            key = (
                fused.page_id,
                fused.sentence_id,
            )

            ranking_rows.append(
                {
                    "claim_id": claim_id,
                    "rank": fused.rank,
                    "page_id": (fused.page_id),
                    "sentence_id": (fused.sentence_id),
                    "rrf_score": (fused.score),
                    "bm25_rank": (bm25_rank_map.get(key)),
                    "dense_rank": (dense_rank_map.get(key)),
                }
            )

        evaluated += 1

        if evaluated % 100 == 0:
            print(f"Evaluated {evaluated:,} / {len(groups):,}")

    if not result_rows:
        raise ValueError("No hybrid retrieval queries were evaluated.")

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

    metrics["mean_fusion_latency_ms"] = mean(
        float(value) for value in result_frame["latency_ms"].to_list()
    )

    metrics["queries_per_second"] = evaluated / elapsed_seconds

    manifest: dict[str, object] = {
        "dataset": "fever",
        "stage": ("hybrid_sentence_retrieval"),
        "split": split,
        "model": model_name,
        "evaluated_queries": (evaluated),
        "source_depth": (source_depth),
        "search_limit": limit,
        "rrf_k": rrf_k,
        "metrics": metrics,
        "elapsed_seconds": (elapsed_seconds),
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
        max_queries=(arguments.max_queries),
        source_depth=(arguments.source_depth),
        limit=arguments.limit,
        rrf_k=arguments.rrf_k,
    )

    metrics_object = manifest["metrics"]

    if not isinstance(
        metrics_object,
        dict,
    ):
        raise TypeError("Invalid metrics.")

    metrics = metrics_object

    print()
    print("FEVER hybrid sentence retrieval benchmark complete.")

    print()

    for k in TOP_K_VALUES:
        hit = float(metrics[f"hit_at_{k}"])

        recall = float(metrics[f"mean_recall_at_{k}"])

        print(f"Hit@{k}: {hit:.4%}")

        print(f"Mean Recall@{k}: {recall:.4%}")

    print()

    print(f"MRR: {float(metrics['mrr']):.4f}")

    print(f"Mean fusion latency: {float(metrics['mean_fusion_latency_ms']):.2f} ms")

    print(f"Queries/sec: {float(metrics['queries_per_second']):.2f}")

    print()

    print(f"Results: {RESULTS_PATH}")

    print(f"Rankings: {RANKINGS_PATH}")

    print(f"Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()

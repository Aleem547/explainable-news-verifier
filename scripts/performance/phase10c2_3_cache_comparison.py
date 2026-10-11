"""Compare baseline versus BGE document-cache hit behavior on a local corpus.

No persistent output, no saved claims, no model weight or threshold changes.
"""

from __future__ import annotations

import argparse
import math
from time import perf_counter

from apps.api.services.retrieval import get_retrieval_pipeline
from ml.retrieval.dense.bge_sentence_ranker import BGESentenceRanker
from ml.retrieval.pipeline import RetrievedEvidence

DEFAULT_CLAIM = "The Eiffel Tower is located in Paris, France."


def measured_retrieval(top_k: int) -> tuple[list[RetrievedEvidence], float]:
    started = perf_counter()
    results = get_retrieval_pipeline().retrieve(DEFAULT_CLAIM, top_k=top_k)
    return results, (perf_counter() - started) * 1000


def compare_evidence(
    before: list[RetrievedEvidence],
    after: list[RetrievedEvidence],
) -> None:
    if len(before) != len(after):
        raise RuntimeError("EVIDENCE MISMATCH: number of results changed; leave cache disabled.")
    for first, second in zip(before, after, strict=True):
        if (first.rank, first.page_id, first.sentence_id, first.text) != (
            second.rank,
            second.page_id,
            second.sentence_id,
            second.text,
        ):
            raise RuntimeError("EVIDENCE MISMATCH: result ranking changed; leave cache disabled.")
        for name in ("bm25_score", "dense_score", "rrf_score", "cross_encoder_score"):
            a = getattr(first, name)
            b = getattr(second, name)
            if a is None or b is None:
                if a != b:
                    raise RuntimeError(f"EVIDENCE MISMATCH: {name}; leave cache disabled.")
            elif not math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-5):
                raise RuntimeError(f"EVIDENCE MISMATCH: {name}; leave cache disabled.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-size", type=int, default=2048)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.cache_size <= 8192:
        parser.error("--cache-size must be between 1 and 8192")
    if not 1 <= args.top_k <= 20:
        parser.error("--top-k must be between 1 and 20")

    started = perf_counter()
    pipeline = get_retrieval_pipeline()
    initialized_ms = (perf_counter() - started) * 1000
    ranker = pipeline.dense_ranker
    if not isinstance(ranker, BGESentenceRanker):
        raise RuntimeError("This comparison requires the production BGE ranker.")
    original_size = ranker.document_cache_size

    try:
        ranker.document_cache_size = 0
        ranker.clear_document_cache()
        baseline, baseline_ms = measured_retrieval(args.top_k)

        ranker.document_cache_size = args.cache_size
        ranker.clear_document_cache()
        filled, fill_ms = measured_retrieval(args.top_k)
        cached, hit_ms = measured_retrieval(args.top_k)

        compare_evidence(baseline, filled)
        compare_evidence(baseline, cached)
        print(f"Retrieval initialization: {initialized_ms:.1f} ms")
        print(f"Baseline (no cache):    {baseline_ms:.1f} ms")
        print(f"Cache fill:             {fill_ms:.1f} ms")
        print(f"Cache hit:              {hit_ms:.1f} ms")
        print(f"Matching ranked results: {len(baseline)}")
        print("Evidence identity, ordering and score-tolerance comparison: PASSED")
        print("Cache is process-local, bounded, and lost when the server restarts.")
    finally:
        ranker.document_cache_size = original_size
        ranker.clear_document_cache()


if __name__ == "__main__":
    main()

"""Standalone, non-mutating diagnostic profiler for FEVER retrieval components.

Invoke from the project root:
    uv run python -m scripts.performance.phase10c2_2_retrieval_benchmark --runs 3 --top-k 5

This only wraps component calls during this benchmark, restoring the original
pipeline immediately afterward. It does not persist any claim or passage text.
"""

from __future__ import annotations

import argparse
import importlib
import statistics
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import dataclass
from functools import wraps
from time import perf_counter
from typing import Any
from unittest.mock import patch

DEFAULT_CLAIM = "The Eiffel Tower is located in Paris, France."
STAGES = ("page_search", "sentence_store", "bm25", "dense", "rrf", "rerank")


@dataclass(frozen=True)
class RetrievalProfile:
    total_ms: float
    stage_ms: dict[str, float]
    counts: dict[str, int]
    output_count: int
    # Compared in memory only, never printed or persisted.
    evidence_signature: tuple[tuple[str, int], ...]


class _TimedMethodProxy:
    """Delegate all behavior, timing exactly one method on a component."""

    def __init__(
        self,
        delegate: Any,
        method_name: str,
        stage: str,
        totals: dict[str, float],
        counts: dict[str, int],
    ) -> None:
        self._delegate = delegate
        self._method_name = method_name
        self._stage = stage
        self._totals = totals
        self._counts = counts

    def __getattr__(self, name: str) -> Any:
        original = getattr(self._delegate, name)
        if name != self._method_name:
            return original

        @wraps(original)
        def measured(*args: Any, **kwargs: Any) -> Any:
            if self._stage == "page_search":
                self._counts["page_search_calls"] += 1
            elif self._stage in {"bm25", "dense", "rerank"} and len(args) >= 2:
                self._counts[f"{self._stage}_input_sentences"] = len(args[1])
            elif self._stage == "sentence_store" and args:
                self._counts["pages_loaded"] = len(args[0])

            started = perf_counter()
            try:
                result = original(*args, **kwargs)
            finally:
                self._totals[self._stage] += (perf_counter() - started) * 1000

            if self._stage == "sentence_store":
                self._counts["source_sentences"] = len(result)
            elif self._stage in {"bm25", "dense", "rerank"}:
                self._counts[f"{self._stage}_output_sentences"] = len(result)
            return result

        return measured


def profile_retrieval_once(
    pipeline: Any,
    claim: str,
    top_k: int,
    *,
    retrieval_module: Any | None = None,
) -> RetrievalProfile:
    """Time one retrieval request, restoring the pipeline even after an exception."""
    if not claim.strip():
        raise ValueError("Claim cannot be blank.")
    if not 1 <= top_k <= 20:
        raise ValueError("Retrieval top_k must be between 1 and 20.")

    module = retrieval_module
    if module is None:
        module = importlib.import_module("ml.retrieval.pipeline")

    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    components = (
        ("page_retriever", "search", "page_search"),
        ("sentence_store", "get_by_page_ids", "sentence_store"),
        ("bm25_ranker", "rank", "bm25"),
        ("dense_ranker", "rank", "dense"),
        ("reranker", "rerank", "rerank"),
    )

    original_fusion = module.reciprocal_rank_fusion

    @wraps(original_fusion)
    def measured_fusion(*args: Any, **kwargs: Any) -> Any:
        started = perf_counter()
        try:
            result = original_fusion(*args, **kwargs)
        finally:
            totals["rrf"] += (perf_counter() - started) * 1000
        counts["rrf_output_sentences"] = len(result)
        return result

    with ExitStack() as stack:
        # Only the local benchmark pipeline instance is modified temporarily.
        for attribute, method, stage in components:
            original_component = getattr(pipeline, attribute)
            stack.enter_context(
                patch.object(
                    pipeline,
                    attribute,
                    _TimedMethodProxy(original_component, method, stage, totals, counts),
                )
            )
        stack.enter_context(patch.object(module, "reciprocal_rank_fusion", measured_fusion))
        started = perf_counter()
        results = pipeline.retrieve(claim, top_k=top_k)
        elapsed_ms = (perf_counter() - started) * 1000

    stage_ms = {stage: totals[stage] for stage in STAGES}
    stage_ms["other"] = max(0.0, elapsed_ms - sum(stage_ms.values()))
    return RetrievalProfile(
        total_ms=elapsed_ms,
        stage_ms=stage_ms,
        counts=dict(counts),
        output_count=len(results),
        evidence_signature=tuple((item.page_id, item.sentence_id) for item in results),
    )


def format_profile(label: str, result: RetrievalProfile) -> str:
    """Format diagnostic timing/counts only; omit claim, evidence and raw IDs."""
    lines = [f"{label}: {result.total_ms:.1f} ms | results={result.output_count}"]
    for stage in (*STAGES, "other"):
        duration = result.stage_ms[stage]
        share = 100 * duration / result.total_ms if result.total_ms else 0.0
        lines.append(f"  {stage:18s} {duration:10.1f} ms ({share:5.1f}%)")
    for name in (
        "page_search_calls",
        "pages_loaded",
        "source_sentences",
        "bm25_input_sentences",
        "dense_input_sentences",
        "rrf_output_sentences",
        "rerank_input_sentences",
    ):
        if name in result.counts:
            lines.append(f"  {name}: {result.counts[name]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3, help="Warm runs, 1 to 10")
    parser.add_argument("--top-k", type=int, default=5, help="API evidence limit, 1 to 20")
    parser.add_argument("--claim", default=DEFAULT_CLAIM, help="Local benchmark claim")
    args = parser.parse_args()
    if not 1 <= args.runs <= 10:
        parser.error("--runs must be between 1 and 10")
    if not 1 <= args.top_k <= 20:
        parser.error("--top-k must be between 1 and 20")
    if not args.claim.strip():
        parser.error("--claim must not be blank")

    from apps.api.services.retrieval import get_retrieval_pipeline

    # ClaimVerificationPipeline.verify requests twice the API evidence limit,
    # capped at 20, to allow its downstream quality screen to select top_k.
    retrieval_top_k = min(20, args.top_k * 2)
    print("Phase 10C.2.2 retrieval microbenchmark; no model or ranking changes.", flush=True)
    print(f"API top_k={args.top_k}, internal retrieval top_k={retrieval_top_k}", flush=True)
    started = perf_counter()
    pipeline = get_retrieval_pipeline()
    print(
        f"Retrieval pipeline initialization: {(perf_counter() - started) * 1000:.1f} ms", flush=True
    )

    first = profile_retrieval_once(pipeline, args.claim, retrieval_top_k)
    print(format_profile("First retrieval", first), flush=True)
    warm: list[RetrievalProfile] = []
    for index in range(args.runs):
        sample = profile_retrieval_once(pipeline, args.claim, retrieval_top_k)
        warm.append(sample)
        print(format_profile(f"Warm retrieval {index + 1}", sample), flush=True)

    print(f"Warm median: {statistics.median(item.total_ms for item in warm):.1f} ms")
    if len({sample.evidence_signature for sample in [first, *warm]}) > 1:
        print("WARNING: Evidence IDs/order changed between benchmark runs.")
        return 2
    print("No model weights, retrieval depth, scoring, API response or evidence were changed.")
    print("Times are local process measurements, not end-to-end HTTP latency.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

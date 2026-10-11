"""Standalone, non-mutating stage profiler for the claim verification pipeline.

Run from the repository root with:
    uv run python -m scripts.performance.phase10c2_benchmark --runs 3 --top-k 5

It instruments only this process and restores the original methods in all cases.
It never sends claims to remote benchmarking services or saves claim text.
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

STAGES = (
    "retrieval",
    "quality_screen",
    "nli",
    "subject_grounding",
    "aggregation",
    "contribution_roles",
)

DEFAULT_CLAIM = "The Eiffel Tower is located in Paris, France."


@dataclass(frozen=True)
class ProfileSample:
    total_ms: float
    stage_ms: dict[str, float]
    verdict: str
    evidence_signature: tuple[tuple[str, int, str, bool], ...]
    assessed_count: int


def _timed_function(delegate: Any, label: str, totals: dict[str, float]) -> Any:
    @wraps(delegate)
    def call(*args: Any, **kwargs: Any) -> Any:
        start = perf_counter()
        try:
            return delegate(*args, **kwargs)
        finally:
            totals[label] += (perf_counter() - start) * 1000

    return call


class _TimedRetriever:
    def __init__(self, delegate: Any, totals: dict[str, float]) -> None:
        self._delegate = delegate
        self._totals = totals

    def retrieve(self, claim: str, *, top_k: int = 10) -> Any:
        start = perf_counter()
        try:
            return self._delegate.retrieve(claim, top_k=top_k)
        finally:
            self._totals["retrieval"] += (perf_counter() - start) * 1000


class _TimedNli:
    def __init__(self, delegate: Any, totals: dict[str, float]) -> None:
        self._delegate = delegate
        self._totals = totals

    def predict(self, claim: str, evidence_texts: Any) -> Any:
        start = perf_counter()
        try:
            return self._delegate.predict(claim, evidence_texts)
        finally:
            self._totals["nli"] += (perf_counter() - start) * 1000


def profile_once(
    pipeline: Any,
    claim: str,
    top_k: int,
    *,
    instrumentation_module: Any | None = None,
) -> ProfileSample:
    """Time one verification without altering its output or persisting any profiling state."""
    if not claim.strip():
        raise ValueError("The benchmark claim must not be blank.")
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20.")

    module = instrumentation_module
    if module is None:
        module = importlib.import_module("ml.verification.evidence_pipeline")

    totals: dict[str, float] = defaultdict(float)
    original_retriever = pipeline.retriever
    original_predictor = pipeline.nli_predictor

    with ExitStack() as stack:
        functions = (
            ("screen_evidence", "quality_screen"),
            ("check_decisive_admissibility", "subject_grounding"),
            ("aggregate_evidence", "aggregation"),
            ("contribution_role", "contribution_roles"),
        )
        for name, stage in functions:
            original = getattr(module, name)
            stack.enter_context(
                patch.object(module, name, _timed_function(original, stage, totals))
            )

        pipeline.retriever = _TimedRetriever(original_retriever, totals)
        pipeline.nli_predictor = _TimedNli(original_predictor, totals)
        try:
            started = perf_counter()
            result = pipeline.verify(claim, top_k=top_k)
            total_ms = (perf_counter() - started) * 1000
        finally:
            pipeline.retriever = original_retriever
            pipeline.nli_predictor = original_predictor

    stages = {stage: totals[stage] for stage in STAGES}
    # Includes Python decision logic, object creation, and instrumentation overhead.
    stages["other"] = max(0.0, total_ms - sum(stages.values()))
    raw_verdict = result.verdict
    verdict = str(getattr(raw_verdict, "value", raw_verdict))
    signature = tuple(
        (item.page_id, item.sentence_id, item.nli_label, item.accepted) for item in result.evidence
    )
    return ProfileSample(
        total_ms=total_ms,
        stage_ms=stages,
        verdict=verdict,
        evidence_signature=signature,
        assessed_count=len(signature),
    )


def format_sample(label: str, sample: ProfileSample) -> str:
    """Print only timings and decision metadata; never expose the claim or evidence text."""
    lines = [
        f"{label}: {sample.total_ms:.1f} ms | verdict={sample.verdict} | "
        f"assessed={sample.assessed_count}"
    ]
    for name in (*STAGES, "other"):
        milliseconds = sample.stage_ms[name]
        share = 100.0 * milliseconds / sample.total_ms if sample.total_ms else 0.0
        lines.append(f"  {name:20s} {milliseconds:10.1f} ms ({share:5.1f}%)")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3, help="Warm repetitions (1 to 10)")
    parser.add_argument("--top-k", type=int, default=5, help="Evidence limit (1 to 20)")
    parser.add_argument("--claim", default=DEFAULT_CLAIM, help="Local benchmark claim")
    args = parser.parse_args()
    if not 1 <= args.runs <= 10:
        parser.error("--runs must be between 1 and 10")
    if not 1 <= args.top_k <= 20:
        parser.error("--top-k must be between 1 and 20")
    if not args.claim.strip():
        parser.error("--claim cannot be empty")

    # Models are imported and loaded only by this explicit benchmark invocation.
    from apps.api.services.verification import get_verification_pipeline

    print("Phase 10C.2 CPU performance baseline (standalone local process)", flush=True)
    print("Loading pipeline. Cold-start can take a while...", flush=True)
    started = perf_counter()
    pipeline = get_verification_pipeline()
    init_ms = (perf_counter() - started) * 1000
    print(f"Cold pipeline initialization: {init_ms:.1f} ms", flush=True)

    first = profile_once(pipeline, args.claim, args.top_k)
    print(format_sample("First request", first), flush=True)

    warm: list[ProfileSample] = []
    for index in range(args.runs):
        sample = profile_once(pipeline, args.claim, args.top_k)
        warm.append(sample)
        print(format_sample(f"Warm request {index + 1}", sample), flush=True)

    median_ms = statistics.median(sample.total_ms for sample in warm)
    print(f"Warm median ({len(warm)} runs): {median_ms:.1f} ms")
    print("Stage times are diagnostic, not HTTP round-trip or billing measurements.")
    print("The retrieval stage includes its internal ranking and retrieval work.")
    print("No checkpoint, thresholds, evidence, or API response schemas were modified.")

    signatures = {(sample.verdict, sample.evidence_signature) for sample in [first, *warm]}
    if len(signatures) != 1:
        print("WARNING: Verdict or evidence labels differed between measured runs.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

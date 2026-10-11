# Phase 10C.2.2 — Retrieval-stage profiling

This patch is **diagnostic only**. It does not modify production retrieval, ML weights, scores, thresholds, or API routes. It adds a temporary, in-process wrapper around the existing retrieval pipeline to measure component time. The wrappers are removed even if a component fails. It does not store the claim or evidence text.

## Install (Windows PowerShell, from repository root)

```powershell
cd C:\Projects\explainable-news-verifier
Expand-Archive -Path "$env:USERPROFILE\Downloads\phase10c2_2_patch.zip" -DestinationPath . -Force
```

## Validate

```powershell
uv run ruff format scripts\performance\phase10c2_2_retrieval_benchmark.py tests\unit\test_phase10c2_2_retrieval_benchmark.py
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest tests\unit\test_phase10c2_2_retrieval_benchmark.py -v
uv run pytest
```

The nine new tests cover timings, counts, cleanup after success/failure, invalid inputs, privacy, and unchanged retrieval outputs. If your previous total was 423, expect 432 collected tests.

## Benchmark

Stop the FastAPI server first to avoid CPU contention. From the repository root:

```powershell
uv run python -m scripts.performance.phase10c2_2_retrieval_benchmark --runs 3 --top-k 5
```

`--top-k 5` mirrors the user's API evidence limit; the verifier actually asks retrieval for `min(20, top_k * 2)`, so the retrieval profiler uses 10. This is important to reproduce the earlier 3.6-second retrieval stage.

Report the component times and document counts. The most important values are `dense`, `rerank`, `source_sentences`, `dense_input_sentences`, and `rerank_input_sentences`.

If stage results differ between runs, the profiler returns a warning and exit status 2; investigate before optimization.

**Do not commit or push yet.**

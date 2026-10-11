# Phase 10C.2.1 — Local model-performance baseline

## Purpose

This profiling-only phase measures where CPU verification time is spent **before** changing any model configurations, confidence thresholds, weights, or retrieval logic.

### Existing performance observations

- `get_verification_pipeline()` caches the first constructed pipeline (`lru_cache(maxsize=1)`).
- The calibrated DeBERTa NLI implementation already batches examples and uses `torch.inference_mode()`.
- The current `ClaimVerificationPipeline.verify()` reports only total pipeline latency.
- The prior web-facing verification showed approximately 17.7 seconds of end-to-end usage time. That observation must not be equated automatically with transformer compute time.

### What the benchmark measures

- **Cold initialization** — pipeline construction and artifact loading in a fresh Python process.
- **First request** — verification immediately following initialization, including any lazy operations in component `retrieve` or `predict`.
- **Warm requests** — repeated requests through the already constructed pipeline.
- **Retrieval** — includes retrieval and internal ranking/reranking, as implemented by the retriever.
- **Evidence quality screening** — `screen_evidence`.
- **NLI** — `predict`.
- **Subject grounding** — cumulative `check_decisive_admissibility` calls.
- **Aggregation and contribution roles** — `aggregate_evidence` and `contribution_role`.
- **Other** — pipeline decision logic, Python object construction and instrumentation overhead.

### Security, privacy and accuracy

- The script runs on the developer's machine; it does not open a server or bypass production authentication.
- It does not call the Next.js web app, so it does **not** measure HTTP, OAuth, Redis, database or network overhead.
- It does not print input claim text or retrieved evidence text.
- Instrumentation exists only inside the profiler Python process and is restored even after an exception.
- The benchmark does not modify checkpoints, calibration files, thresholds, model parameters or API response schemas.
- Repeated requests could compete with an already-running inference process for CPU/RAM; stop the running backend during the benchmark.

## Run

```powershell
cd C:\Projects\explainable-news-verifier
uv run pytest tests\unit\test_phase10c2_benchmark.py -v
uv run python -m scripts.performance.phase10c2_benchmark --runs 3 --top-k 5
```

Running the script may take several minutes on CPU if the checkpoint or retrieval indexes load slowly. Keep the terminal open and send the timing report. **Do not change PyTorch thread count, batch size, `top_k`, or NLI max sequence length before establishing this baseline.**

## Interpretation

- If cold initialization dominates, consider model and artifact-loading improvements later.
- If retrieval dominates, profile the retrieval pipeline's dense retrieval and cross-encoder reranker next.
- If NLI dominates, benchmark PyTorch CPU threading and smaller controlled batches without changing the calibrated model.
- If subject grounding or aggregation dominates, inspect repeated expensive Python operations.
- Repeat the same benchmark after every optimization. Compare the verdict and evidence decisions, not only latency.

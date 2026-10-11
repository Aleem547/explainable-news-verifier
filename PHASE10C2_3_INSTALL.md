# Phase 10C.2.3 — bounded BGE document embedding cache

This is an opt-in optimization for *repeated or overlapping Wikipedia candidate sentences*. It does not change the BGE checkpoint, BM25, RRF, cross-encoder, NLI or evidence thresholds. Default cache size is **0** (disabled) until validated.

## Install (VS Code PowerShell, project root)

Save the ZIP as `%USERPROFILE%\Downloads\phase10c2_3_patch.zip` and run:

```powershell
cd C:\Projects\explainable-news-verifier
Expand-Archive -Path "$env:USERPROFILE\Downloads\phase10c2_3_patch.zip" -DestinationPath . -Force
```

The ZIP replaces only `ml/retrieval/dense/bge_sentence_ranker.py` and `ml/retrieval/factory.py`, and adds a test, a diagnostic comparison script, and documentation.

## Static validation and tests

```powershell
uv run ruff check --fix ml\retrieval\dense\bge_sentence_ranker.py ml\retrieval\factory.py scripts\performance\phase10c2_3_cache_comparison.py tests\unit\test_phase10c2_3_bge_cache.py
uv run ruff format ml\retrieval\dense\bge_sentence_ranker.py ml\retrieval\factory.py scripts\performance\phase10c2_3_cache_comparison.py tests\unit\test_phase10c2_3_bge_cache.py
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest tests\unit\test_phase10c2_3_bge_cache.py -v
uv run pytest
```

Previous full suite: 432 tests. Added here: 18 tests. Expected **450**, assuming the rest of the repository is unchanged.

## Accuracy/latency A/B check without permanent configuration

Stop your Uvicorn process with Ctrl+C so it does not compete for model memory/CPU. The script uses the *same* loaded BGE model for both runs and compares final retrieved evidence IDs, ordering and scores:

```powershell
uv run python -m scripts.performance.phase10c2_3_cache_comparison --cache-size 2048 --top-k 10
```

If comparison fails, **do not enable caching**; report the output. Query vectors are recomputed for every claim. Cache entries are keyed by page, sentence number **and exact sentence text**.

## Compare retrieval stage times (optional, after accuracy check)

```powershell
$env:VERIFIER_BGE_DOCUMENT_CACHE_SIZE="2048"
uv run python -m scripts.performance.phase10c2_2_retrieval_benchmark --runs 3 --top-k 5
Remove-Item Env:VERIFIER_BGE_DOCUMENT_CACHE_SIZE -ErrorAction SilentlyContinue
```

This opt-in env var must be set *in the server process environment before model construction*. Editing a `.env` file that your process has not loaded will not set it automatically. Restart the server after changing the setting because the retrieval factory is cached.

`VERIFIER_BGE_DOCUMENT_CACHE_SIZE` range is **0–8192**; `0` disables caching. `2048` embeddings of dimension 384 using float32 require ~3 MiB just for vectors, plus Python metadata and transient model memory. Results are approximate; memory usage depends on model/dtype and keys. Cache is per process, not shared across workers, and is lost when restarted. This is not a full corpus embedding index; first-time candidate sentences must still be encoded.

Don't commit or push until the user explicitly authorizes it.

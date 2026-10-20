# Phase 13D.8 — Final Cross-Source Integration and Regression Validation

**Scope:** Tests only. No new API, production pipeline deployment, database migration, news fetch, model training, or changed decision policy.

## Test design

1. `tests/unit/test_phase13d8_final_contracts.py` checks real Phase 13D.6 + 13D.7 report contracts with synthetic NLI scores: provisional support/refutation, mixed evidence, insufficient evidence, duplicated passages, identity/tamper checks, output stability, and the permanent `NOT_ESTABLISHED` source-independence limit.
2. `tests/integration/test_phase13d8_full_pipeline_db.py` exercises the real PostgreSQL retrieval/audit/normalization/source-dependency/NLI-agreement/decision path using **three synthetic article snapshots** across three synthetic domains. The first two share identical full article content and must be treated as a single dependency-risk unit; the third is different. The test injects a **controlled predictor** to test support/refute/neutral and fail-closed behavior. **This is not a model-accuracy test.**
3. The database test opens an explicit outer transaction, inserts the fixture, and rolls everything back. It re-queries the synthetic URLs afterward to confirm deletion; SQLAlchemy async engine is disposed before the loop is closed.
4. The runner executes all tracked `test_phase13d*.py` unit suites, then the local integration test. An optional flag reruns the existing DeBERTa smoke test.

## Local Windows procedure

In VS Code PowerShell with Docker Desktop running:

```powershell
cd C:\Projects\explainable-news-verifier
& .\scripts\phase13d8\run_local_phase13d8.ps1
git diff --check
git status -sb
```

Optional, for the full frozen-model smoke already used in Phase 13D.5:

```powershell
& .\scripts\phase13d8\run_local_phase13d8.ps1 -IncludeModelSmoke
```

The script reads PostgreSQL credentials **only from the running local Docker container**, keeps those values solely in the process environment temporarily, and restores previous environment variables in `finally`. It connects to `127.0.0.1:5432`. No credentials are written to disk or included in Git.

## Acceptance conditions

- Every Phase 13D unit/regression test passes.
- The PostgreSQL test passes with synthetic data and zero residual fixture rows.
- The report includes every assessed passage ID, and grouped duplicates do not count as separate confirmation units.
- Tampered passage input aborts before NLI model calls.
- All positive or negative stances remain provisional, and `independent_corroboration_established` stays `False`.
- No merges into `main`; no AWS/Vercel changes.

## Known limitations / follow-up

- PostgreSQL full-text search needs indexing and benchmarks before production-scale use.
- Dependency-risk grouping identifies reused reporting but **does not prove editorial independence**. The current decision contract intentionally never establishes independent corroboration.
- The database end-to-end integration uses mocked NLI scores, not actual DeBERTa; the separate Phase 13D.5 model smoke validates real CPU inference in isolation.
- The test does **not** exercise live news-site retrieval, permissions, public API authentication, UI, operational reliability, or factual accuracy. Those remain in Phase 13E and 13F.
- A positive *independent* corroboration claim would require a separately validated affirmative independence standard; do not rename provisional support as independently verified during frontend/API integration.

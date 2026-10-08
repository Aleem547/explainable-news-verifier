# Phase 8E-2 — Opt-in subject-focused page discovery

## Why this exists

The 60-claim FEVER validation diagnosed two coupled problems: many decisive claims abstain because relevant gold evidence is absent from the assessed sentences, but increasing `top_k` also introduces unrelated high-confidence NLI decisions. Phase 8E-1's admissibility guard blocked the *Rio's sequel* / *An Inconvenient Sequel* false refutation. A safer next experiment is to look for *better candidate pages* without weakening that guard.

This package changes only the **retrieval page-discovery stage**. It leaves the existing sentence-level BM25 + dense + RRF + cross-encoder reranking sequence intact; all sentence scorers continue to use the **original claim**, not the expanded query. Hypothetical titles (for example, ``Rio 2`` derived from ``Rio's sequel``) are **search hints, not accepted aliases or factual claims**. The output still passes the existing evidence hygiene, subject admissibility, calibrated NLI, and page aggregation steps.

**Important:** This is an experiment, not a validated model improvement. The experiment is **OFF by default**. We must compare it against the same 60 validation claims and seed before enabling it as a permanent default. No Git commit or push until Phase 8 finishes.

## Included files

- `ml/retrieval/pipeline.py` — **complete replacement** preserving the original interface, with an optional page-discovery expansion.
- `ml/retrieval/subject_queries.py` — **new** conservative subject query builder.
- `tests/unit/test_subject_queries.py` — new unit tests.
- `tests/unit/test_subject_expansion_pipeline.py` — new fake-retriever integration tests.
- `PHASE8E2_README.md` — this guide.

`apps/api/services/retrieval.py`, the verification pipeline, and your FastAPI routes are **not replaced or modified**.

## Windows PowerShell — install

1. Stop FastAPI if running (`Ctrl+C`).
2. Download `phase8e2_subject_retrieval.zip` into your Downloads folder.
3. From the repository root, make a backup of the one file being replaced:

```powershell
cd C:\Projects\explainable-news-verifier
Test-Path "$HOME\Downloads\phase8e2_subject_retrieval.zip"

$backup = Join-Path $env:TEMP "verifier_phase8e2_backup"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
Copy-Item ml\retrieval\pipeline.py "$backup\retrieval_pipeline.py" -Force

Expand-Archive `
  -LiteralPath "$HOME\Downloads\phase8e2_subject_retrieval.zip" `
  -DestinationPath "." `
  -Force
```

4. Verify file placement:

```powershell
Test-Path ml\retrieval\subject_queries.py
Test-Path tests\unit\test_subject_expansion_pipeline.py
uv run ruff check .
uv run mypy apps ml scripts
uv run pytest
```

Prior to this experiment, 140 tests were passing. This package adds 15; if no other tests have been added, **155 tests** should now be collected.

## Baseline behavior / toggle

Default: original page search only, unchanged behavior.

Enable supplemental page search in the shell running the evaluator or FastAPI:

```powershell
$env:VERIFIER_SUBJECT_QUERY_EXPANSION = "1"
```

Disable it again:

```powershell
Remove-Item Env:VERIFIER_SUBJECT_QUERY_EXPANSION -ErrorAction SilentlyContinue
```

For every claim, the experiment searches the original query first, then up to two conservative subject-focused queries. Newly discovered pages are deduplicated; the total page pool is bounded to 32 by default. The config can also enable it directly with `RetrievalPipelineConfig(enable_subject_query_expansion=True)`, but the environment variable allows testing without editing `ml/retrieval/factory.py` or the FastAPI service.

## Optional Rio smoke test (no new model training)

In terminal 1, set the environment variable and start FastAPI:

```powershell
$env:VERIFIER_SUBJECT_QUERY_EXPANSION = "1"
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

In terminal 2:

```powershell
$body = @{claim = "Rio's sequel is an American musical comedy film."; top_k = 10} | ConvertTo-Json
$r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/verify" -Method Post -ContentType "application/json" -Body $body
$r | Select-Object claim, verdict, assessed_count, admissibility_blocked_count
$r.evidence | Format-Table rank, page_id, nli_label, accepted, admissibility_reason
```

We hope to find a directly relevant page (`Rio_2` or an explicit sequel reference). **It is not guaranteed**: the page retriever, sentence ranking and corpus contents determine results. In particular, the safeguard should continue to prevent `An_Inconvenient_Sequel` from being decisive for this claim.

## Controlled 60-claim validation comparison

Stop FastAPI to avoid competing for CPU. Preserve your existing Phase 8E-1 validation report as the **OFF** baseline. Before starting, note the baseline report folder path.

Run the **ON** experiment in one PowerShell session:

```powershell
cd C:\Projects\explainable-news-verifier
$env:VERIFIER_SUBJECT_QUERY_EXPANSION = "1"
uv run python -m scripts.evaluation.evaluate_fever_verification `
  --split validation `
  --max-examples 60 `
  --seed 42 `
  --top-k 5

$trial = Get-ChildItem .\reports\evaluation -Directory |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

Get-Content (Join-Path $trial.FullName "REPORT.md")
Import-Csv (Join-Path $trial.FullName "failures.csv") |
  Group-Object failure_type |
  Select-Object Name, Count

@{ phase = "8E-2"; subject_query_expansion = $true; top_k = 5; seed = 42; split = "validation" } |
  ConvertTo-Json |
  Set-Content (Join-Path $trial.FullName "retrieval_experiment_config.json")

Remove-Item Env:VERIFIER_SUBJECT_QUERY_EXPANSION -ErrorAction SilentlyContinue
```

Compare against the prior 60-claim Phase 8E-1 report: wrong decisive verdicts, abstention on decisive gold, macro F1, decision coverage, gold-page / gold-sentence / complete-set *assessed* alignment, and latency. Confirm the **selection hash is identical**. Keep in mind that gold alignment here is about assessed evidence, not raw retrieval recall. We should **not** automatically make this experimental mode the default even if one metric improves.

If successful with `top_k=5`, consider a second controlled experiment at `top_k=10` only after reviewing failure cases.

## Rollback

Stop FastAPI, remove the environment variable and restore the original pipeline:

```powershell
Remove-Item Env:VERIFIER_SUBJECT_QUERY_EXPANSION -ErrorAction SilentlyContinue
$backup = Join-Path $env:TEMP "verifier_phase8e2_backup"
Copy-Item "$backup\retrieval_pipeline.py" ml\retrieval\pipeline.py -Force
uv run pytest
```

The extra query module and tests can remain unused or can be removed. No model, dataset, database, or Git history is changed by this package.

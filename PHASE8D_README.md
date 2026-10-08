# Phase 8D — End-to-end FEVER verification evaluation

This stage adds **an evaluation script only**. It does not modify the FastAPI application, existing verification pipeline, trained models, or databases. No Git operations are performed.

## Windows / PowerShell installation

From `C:\Projects\explainable-news-verifier`, stop a running FastAPI server with **Ctrl+C** to avoid contention for CPU and RAM. Download `phase8d_verification_benchmark.zip` into Windows Downloads. Run:

```powershell
cd C:\Projects\explainable-news-verifier
Test-Path "$HOME\Downloads\phase8d_verification_benchmark.zip"
Expand-Archive -LiteralPath "$HOME\Downloads\phase8d_verification_benchmark.zip" -DestinationPath . -Force
Test-Path ml\verification\benchmark.py
Test-Path scripts\evaluation\evaluate_fever_verification.py
Test-Path tests\unit\test_verification_benchmark.py
```

All three Python-file checks must show `True`. If the ZIP isn't in Downloads, press Ctrl+J in Chrome, locate it, and copy it to Downloads or replace the archive path with the true location.

## 1. Static checks and unit tests

```powershell
uv run ruff check .
uv run mypy apps ml scripts
uv run pytest
```

The new tests cover reproducible stratified sampling, mapping all four outcomes, class-level scores, coverage/abstention, multi-sentence evidence sets, and failure categorization. No model download is needed for the unit tests.

## 2. Dataset readiness check (loads NO models)

```powershell
uv run python -m scripts.evaluation.evaluate_fever_verification --dry-run --max-examples 12 --seed 42
```

This reads `data\processed\fever\claims.parquet` and `data\processed\fever\resolved_evidence.parquet` where available. It displays balanced sample counts and how many claims have complete annotated gold evidence sets. If an input schema differs, stop and share the exact error; do not modify test labels or silently remap columns.

## 3. First end-to-end evaluation (small diagnostic set)

```powershell
uv run python -m scripts.evaluation.evaluate_fever_verification --max-examples 12 --seed 42 --top-k 5
```

This calls **the same local CPU verification pipeline** used by `POST /api/v1/verify` sequentially. It may take a minute or more depending on model loading and PC performance. `--max-examples 12` selects approximately four claims from each FEVER class. The selected IDs are deterministic for the given seed and dataset. It does not retrain anything.

**Do not run the benchmark in parallel with the FastAPI server** unless you intentionally provision sufficient CPU and memory.

## 4. Inspect the report

Each run creates an independent folder like:

```text
reports/evaluation/phase8d_test_12_seed42_YYYYMMDDTHHMMSSZ/
  manifest.json             - selection fingerprint, input-file metadata, code hashes, parameters
  selection.json            - explicit evaluated claim IDs, labels and texts
  cases.jsonl               - each case's verdict, assessed sentences, scores and roles
  metrics.json              - aggregate scores, per-class precision/recall/F1, coverage and gold hits
  confusion_matrix.csv      - 3 gold classes x 4 predicted categories
  failures.csv              - mismatched cases and diagnostic (non-causal) flags
  REPORT.md                 - concise human-readable diagnostic report
```

PowerShell to view latest report:

```powershell
$latest = Get-ChildItem .\reports\evaluation -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content (Join-Path $latest.FullName "REPORT.md")
Import-Csv (Join-Path $latest.FullName "failures.csv") | Select-Object -First 10 | Format-Table
```

After the 12-claim trial succeeds, run a **larger benchmark**, e.g. `--max-examples 90 --seed 42 --top-k 5`. This may take several minutes on CPU. **Do not alter evaluation thresholds or evidence filters based on test results and then reuse the same test split as an unbiased final score.** Use validation data to develop, and reserve a truly untouched benchmark for final estimates.

## What the metrics mean

- **Benchmark label agreement** maps `SUPPORTING_EVIDENCE → SUPPORTS`, `REFUTING_EVIDENCE → REFUTES`, `INSUFFICIENT_EVIDENCE → NOT ENOUGH INFO`; `CONFLICTING_EVIDENCE → CONFLICT` is treated as a non-match.
- **Macro F1** is computed over the three FEVER gold classes; conflict outputs count as missed true labels.
- **Decision coverage** is the fraction of claims with a SUPPORTS/REFUTES prediction. INSUFFICIENT and CONFLICTING are *abstentions* for coverage calculations.
- **Decided accuracy** is accuracy among SUPPORTS/REFUTES predictions only, NOT the fraction of all claims correctly handled.
- **Failure diagnostic flags** highlight gold evidence not assessed, NLI predictions below threshold, and entity filtering. These are investigation cues, NOT established root causes.
- **Assessed evidence alignment** compares assessed (post-filter) sentences with FEVER's complete gold annotation sets. This is **not raw retrieval recall**, which cannot be measured using only the current API result. It excludes cases without complete resolved gold annotation sets from the denominator.
- **NEI caveat**: FEVER's NOT ENOUGH INFO label is an annotation about the dataset's evidence; a system abstention is not itself proof that the claim belongs to that class. Treat mapped agreement as a convenient proxy, not an authoritative end-to-end truth score.
- **Independence caveat**: The retrieval corpus is Wikipedia-derived; this evaluation does not establish independent-source corroboration.

## Failure/recovery

Unexpected failures stop the run and mark `manifest.json` as `FAILED_PARTIAL`. Already completed case records remain in `cases.jsonl`. No benchmark score is issued for an incomplete run. Rerun with the same options after fixing the issue to create a new report folder.

## Additional work after 8D

A future stage should record **the entire pre-screen retrieval candidate list** to calculate raw retrieval Recall@K, and add truly independent sources and a withheld gold evaluation set. Avoid reporting broad production accuracy from 12 diagnostic cases.

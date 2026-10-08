# Phase 8B — Title-based Entity Relevance (local development)

This package is built for the **Phase 8A** state of Explainable News Verifier. It does not require model retraining and does not touch Git.

## Files

- `ml/verification/entity_relevance.py` — **new**; decode FEVER page titles and compare qualified variants against locative claims.
- `ml/verification/evidence_quality.py` — **full replacement**; calls the Phase 8B guard before selecting evidence for NLI; retains the Phase 8A hygiene rules.
- `apps/api/schemas/verification.py` — **full replacement**; adds two new audit exclusion reasons without removing existing response fields.
- `tests/unit/test_entity_relevance.py` — **new**; 12 test cases for original and qualified titles, false location claims, correct replica claims, abstention, and API audit reasons.

`ml/verification/evidence_pipeline.py`, the retrieval pipeline and the NLI weights are **not replaced**. The existing `screen_evidence()` hook already feeds the Phase 8B guard into Phase 7E/7F.

## Windows PowerShell setup

Stop your running FastAPI development server with Ctrl+C before extracting.

From `C:\Projects\explainable-news-verifier`:

```powershell
cd C:\Projects\explainable-news-verifier
Test-Path "$HOME\Downloads\phase8b_entity_relevance.zip"
```

Only if the ZIP exists there, save backups:

```powershell
$backup = Join-Path $env:TEMP 'verifier_phase8b_backup'
New-Item -ItemType Directory -Force -Path $backup | Out-Null
Copy-Item ml\verification\evidence_quality.py "$backup\evidence_quality.py"
Copy-Item apps\api\schemas\verification.py "$backup\verification_schema.py"
```

Extract directly into the project, not into an extra nested folder:

```powershell
Expand-Archive -LiteralPath "$HOME\Downloads\phase8b_entity_relevance.zip" -DestinationPath . -Force
Test-Path ml\verification\entity_relevance.py
Test-Path tests\unit\test_entity_relevance.py
```

Then run:

```powershell
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run mypy apps ml scripts
uv run pytest
```

The existing 86 tests plus 12 new tests should yield 98 tests, provided nothing else changes. If any check fails, stop and share the error.

Restart:

```powershell
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

In a new PowerShell terminal:

```powershell
$body = @{claim='The Eiffel Tower is located in Paris'; top_k=5} | ConvertTo-Json
$response = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/verify' -Method Post -ContentType 'application/json' -Body $body
$response | Select-Object claim,verdict,retrieved_count,assessed_count,quality_excluded_count
$response.quality_exclusions | Format-Table rank,page_id,reason
```

Look for `ENTITY_VARIANT_MISMATCH` on off-target qualified locations. Do **not** assume any verdict is correct without checking the underlying text. A result of `INSUFFICIENT_EVIDENCE` is preferable to guessing if the retrieved pool is off-target.

## Limits and safeguards

These are **narrow lexical rules**, not entity linking, geographical knowledge or source credibility judgments. They apply primarily to unqualified *location claims* containing a multiword entity title and are disabled for many replica/comparison claims. A fully qualified subject such as `the Eiffel Tower in Paris, Texas` is handled differently from an unqualified subject with the claimed destination `is located in Paris, Texas`.

Potentially relevant evidence can be conservatively excluded if Wikipedia uses a noncanonical title; inspect `quality_exclusions` and treat these as a *precision-first heuristic*. Unknown, historical, ambiguous and cross-source cases require richer entity linking and further evaluation. Existing model calibration on curated FEVER pairs is not guaranteed to hold after these filters.

**Do not commit or push unless you later choose to.**

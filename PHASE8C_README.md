# Phase 8C — Auditable evidence aggregation

## Scope

This is a **conservative page-grouping upgrade**, not a calibrated claim-level truth
estimator or a genuine cross-source corroboration engine.

- Keep all existing request fields, response fields, endpoints, and trained models.
- For each Wikipedia page, one highest-confidence accepted NLI sentence per
  stance is marked PRIMARY_SUPPORT or PRIMARY_REFUTATION.
- Other accepted decisive sentences from that same page are annotated
  SAME_PAGE_ADDITIONAL; they do not inflate the number of primary page decisions.
- An accepted contradiction and entailment are never cancelled out by summing
  confidences. Even within one Wikipedia page, they yield CONFLICTING_EVIDENCE.
- No accepted decisive NLI sentence yields INSUFFICIENT_EVIDENCE.
- All candidate assessments remain in `evidence`. Old fields remain available.
- `corroboration_status=NOT_ESTABLISHED_SINGLE_CORPUS` clearly communicates
  that distinct Wikipedia pages **are not** independent external sources.
- Do **not** interpret primary counts as calibrated claim-level probabilities.

## Changed / added files

- `ml/verification/evidence_aggregation.py` (new)
- `ml/verification/evidence_pipeline.py` (full replacement)
- `apps/api/schemas/verification.py` (full replacement)
- `tests/unit/test_evidence_aggregation.py` (new)
- `PHASE8C_README.md` (new)

## Install (PowerShell, project root)

Stop FastAPI first (Ctrl+C). Back up existing files, then extract the ZIP
into the repository root. If the ZIP is in Downloads, use its actual location.

```powershell
cd C:\Projects\explainable-news-verifier
$backup = Join-Path $env:TEMP 'verifier_phase8c_backup'
New-Item -ItemType Directory -Force -Path $backup | Out-Null
Copy-Item ml\verification\evidence_pipeline.py "$backup\evidence_pipeline.py"
Copy-Item apps\api\schemas\verification.py "$backup\verification_schema.py"
Expand-Archive -LiteralPath "$HOME\Downloads\phase8c_evidence_aggregation.zip" -DestinationPath . -Force
```

## Local checks

```powershell
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run mypy apps ml scripts
uv run pytest
```

## API smoke test

Start in one terminal:

```powershell
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

In a second terminal:

```powershell
$body = @{claim='The Eiffel Tower is located in Paris';top_k=5} | ConvertTo-Json
$response = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/verify' -Method Post -ContentType 'application/json' -Body $body
$response | Select-Object claim,verdict,aggregation_reason,supporting_pages,refuting_pages,supporting_evidence_count,refuting_evidence_count,primary_evidence_count,corroboration_status
$response.evidence | Format-Table page_id,nli_label,nli_confidence,accepted,contribution_role
```

## Limitations / next step

This version does not link real-world entities, verify temporal validity, assess
publisher credibility, fetch independent external sources, or calibrate the
aggregate verdict. Phase 8D must evaluate errors and ablations on a leakage-safe
holdout before claiming better accuracy or trustworthiness.

Do not commit or push unless you choose to.

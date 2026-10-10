# Phase 10A.6 — evidence decision correctness and explainability

This archive contains complete replacement files at **their repository-relative paths**.

## Replacements

1. `ml/verification/evidence_pipeline.py`: high-confidence NEUTRAL evidence is **never accepted**; keeps the 0.90 threshold and original named-subject check. Adds `decision_reason` for accepted/neutral/below-threshold/subject-not-grounded outcomes.
2. `apps/api/schemas/verification.py`: adds an **optional**, backward-compatible `decision_reason` response field. No migrations required.
3. `tests/unit/test_evidence_verification_pipeline.py`: adds focused regression tests for neutral, threshold, grounding, supported/refuted verdicts, and schema compatibility.
4. `apps/web/src/components/verification/evidence-card.tsx`: clear per-evidence rejection explanations, with a fallback derived from existing response fields if the backend does not yet transmit `decision_reason`. Applies only display-level FEVER bracket decoding and lets users reveal the exact original text.
5. `apps/web/src/components/verification/verification-workspace.tsx`: passes the returned threshold to each evidence card.

The two other files you supplied (`decisive_admissibility.py`, `evidence_aggregation.py`) are **not changed**. The aggregator already ignores neutral evidence; we are fixing the inconsistent `accepted` flag upstream.

## Install on Windows PowerShell (repository root)

First **stop the Next.js dev server**; stop/restart FastAPI after installing so the Python changes are loaded. The Docker stack can remain running.

```powershell
cd C:\Projects\explainable-news-verifier

$files = @(
    'ml\verification\evidence_pipeline.py',
    'apps\api\schemas\verification.py',
    'tests\unit\test_evidence_verification_pipeline.py',
    'apps\web\src\components\verification\evidence-card.tsx',
    'apps\web\src\components\verification\verification-workspace.tsx'
)
$backup = Join-Path $env:TEMP ('phase10a6_backup_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
foreach ($file in $files) {
    $destination = Join-Path $backup $file
    New-Item -ItemType Directory -Force -Path (Split-Path $destination -Parent) | Out-Null
    Copy-Item -LiteralPath $file -Destination $destination
}
Write-Host "Backup: $backup"

Expand-Archive -LiteralPath "$HOME\Downloads\phase10a6_reliability_patch.zip" -DestinationPath . -Force
```

## Validate Python

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy apps ml scripts
uv run pytest
```

## Validate frontend

```powershell
cd C:\Projects\explainable-news-verifier\apps\web
npm run lint
npx tsc --noEmit
npm run build
```

## Test after restarting FastAPI and Next.js dev

**FastAPI terminal:**

```powershell
cd C:\Projects\explainable-news-verifier
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

**Next.js terminal:**

```powershell
cd C:\Projects\explainable-news-verifier\apps\web
npm run dev
```

**Third terminal:**

```powershell
$body = @{ claim = 'The Eiffel Tower is located in Paris.'; top_k = 10 } | ConvertTo-Json
$result = Invoke-RestMethod -Uri 'http://127.0.0.1:3000/api/verification' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 180
$result.evidence | Select-Object rank, page_id, nli_label, nli_confidence, accepted, decision_reason, admissibility_reason | Format-Table -AutoSize
```

No NEUTRAL row should have `accepted=True`. High-confidence unmatched subjects should stay not accepted. Below-threshold entailments should stay not accepted. The `decision_reason` field will be present **only if** your FastAPI service serializes it. The UI will still display correct reasons by deriving them from the already available fields if the service does not yet pass through the new property. If `decision_reason` is blank, supply `apps/api/services/verification.py` and `apps/api/routes/verification.py` for a focused serialization update, rather than changing those unknown files blindly.

The production verification endpoint remains intentionally disabled pending authentication/rate-limiting. This patch does not enable it and does not change model scores, thresholds, or source-independence claims.

## Testing evidence

- Python `compileall` passed on the replacement files.
- TypeScript TSX parser returned zero syntax diagnostics on the modified UI files.
- **17 targeted tests passed in an isolated stub harness**, not against your complete repo. Run the full commands above locally before confirming completion.

**Do not Git push until Phase 10 is completed**, as planned.

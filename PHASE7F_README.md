# Phase 7F — Verification API

The new `POST /api/v1/verify` endpoint calls the existing Phase 7E retrieval + calibrated
DeBERTa NLI pipeline. It does not retrain models or modify retrieval/classification routes.

## Contents

- `apps/api/main.py` — complete replacement; adds one router and preserves the original routes.
- `apps/api/routes/verification.py` — FastAPI route, logging and guarded error responses.
- `apps/api/services/verification.py` — lazy singleton loader and CPU concurrency guard.
- `apps/api/schemas/verification.py` — request/response models.
- `tests/unit/test_verification_api.py` — mocked API tests (do not load ML models).

## Windows installation

From `C:\Projects\explainable-news-verifier` in PowerShell:

```powershell
Copy-Item apps\api\main.py "$env:TEMP\verifier_main_before_phase7f.py"
Expand-Archive -LiteralPath "$HOME\Downloads\phase7f_verification_api.zip" -DestinationPath . -Force
Test-Path apps\api\routes\verification.py
Test-Path apps\api\services\verification.py
Test-Path apps\api\schemas\verification.py
Test-Path tests\unit\test_verification_api.py
```

## Code checks

```powershell
uv run ruff check . --fix
uv run ruff format .
uv run ruff check .
uv run mypy apps ml scripts
uv run pytest
```

## Run API

```powershell
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000/docs` and try `POST /api/v1/verify`, or in a **second** terminal:

```powershell
$body = @{ claim = "The Eiffel Tower is located in Paris"; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/verify" -Method Post -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 8
```

## HTTP status codes

- `200`: evidence-based verification result (with per-evidence NLI probabilities).
- `422`: invalid claim or `top_k`.
- `429`: local CPU verifier busy; retry using the `Retry-After` header.
- `503`: required model/calibration/retrieval artifacts unavailable.
- `500`: unexpected server failure.

Model weights are loaded only upon the first verification request. This local development
endpoint has no authentication and is **not ready for public deployment**. It does not
provide a calibrated claim-level probability or verification against independent live sources.

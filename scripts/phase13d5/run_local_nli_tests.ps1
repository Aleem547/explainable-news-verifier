param(
    [switch]$IncludeModelSmoke
)

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
$python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Project virtual environment was not found" }

Write-Host "Phase 13D.5: offline report and orchestration tests (no network, no database)."
& $python -m unittest discover -s tests/unit -p "test_phase13d5_external_evidence_nli.py" -v
if ($LASTEXITCODE -ne 0) { throw "Phase 13D.5 unit tests failed" }

if ($IncludeModelSmoke) {
    Write-Host "Running existing frozen, CPU-based DeBERTa checkpoint smoke test."
    & $python -m unittest discover -s tests/integration -p "test_phase13d5_real_model_smoke.py" -v
    if ($LASTEXITCODE -ne 0) { throw "Phase 13D.5 real-model smoke test failed" }
}
Write-Host "Phase 13D.5 selected checks passed."

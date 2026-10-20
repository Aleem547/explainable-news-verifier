$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repo
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Project .venv Python not found: $python"
}
if ((git branch --show-current).Trim() -ne "feat/phase13-cross-source") {
    throw "Expected feat/phase13-cross-source. No files have been changed."
}
Write-Host "Running Phase 13D.6 evidence agreement tests (offline; no DB, model, or HTTP)."
& $python -m unittest discover -s tests/unit -p "test_phase13d6_evidence_agreement.py" -v
if ($LASTEXITCODE -ne 0) { throw "Phase 13D.6 unit tests failed" }
Write-Host "Running Phase 13D.5 offline regression tests."
& $python -m unittest discover -s tests/unit -p "test_phase13d5_external_evidence_nli.py" -v
if ($LASTEXITCODE -ne 0) { throw "Phase 13D.5 regression tests failed" }
Write-Host "Phase 13D.6 selected tests passed. No data, services, or Git history changed."

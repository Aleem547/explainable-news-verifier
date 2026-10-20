param(
    [switch]$IncludeRegressions
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repo

$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Project virtual environment is missing: $python"
}

$branch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne "feat/phase13-cross-source") {
    throw "Expected feat/phase13-cross-source development branch."
}

Write-Host "Running Phase 13E.1 offline unified orchestration tests (no network, no AWS)."
& $python -m unittest discover -s tests/unit -p "test_phase13e1_unified_orchestrator.py" -v
if ($LASTEXITCODE -ne 0) { throw "Phase 13E.1 unit tests failed." }

if ($IncludeRegressions) {
    foreach ($pattern in @(
        "test_phase13d7_corroboration_decision.py",
        "test_phase13d8_final_contracts.py"
    )) {
        Write-Host "Running regression suite: $pattern"
        & $python -m unittest discover -s tests/unit -p $pattern -v
        if ($LASTEXITCODE -ne 0) { throw "Regression suite failed: $pattern" }
    }
}

Write-Host "Phase 13E.1 selected tests passed. No production operations performed."

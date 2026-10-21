param(
    [switch]$IncludeRegressions
)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))

$python = Join-Path (Get-Location).Path ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment not found: .venv\Scripts\python.exe"
}

function Invoke-TestFile([string]$file) {
    $path = Join-Path "tests\unit" $file
    if (-not (Test-Path $path)) { throw "Missing test file: $path" }
    Write-Host "Running $file (local offline tests)" -ForegroundColor Cyan
    & $python -m unittest discover -s tests/unit -p $file -v
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed: $file (exit code $LASTEXITCODE)"
    }
}

Invoke-TestFile "test_phase13e5_multi_claim_verification.py"
if ($IncludeRegressions) {
    Invoke-TestFile "test_phase13e4_claim_candidates.py"
    Invoke-TestFile "test_phase13e3_pasted_article.py"
    Invoke-TestFile "test_phase13e2_article_url_preparation.py"
    Invoke-TestFile "test_phase13e1_unified_orchestrator.py"
}
Write-Host "Phase 13E.5 selected tests passed. No model, HTTP, or database operations performed." -ForegroundColor Green

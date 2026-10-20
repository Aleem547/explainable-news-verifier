param(
    [switch]$IncludeRegressions,
    [switch]$IncludeExtractorSmoke
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repo

$branch = (git branch --show-current).Trim()
if ($branch -ne "feat/phase13-cross-source") {
    throw "Wrong branch: $branch. Switch to the Phase 13 feature branch first."
}

$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Project virtual-environment Python not found: $python"
}

function Invoke-TestSuite {
    param([string]$Directory, [string]$Pattern)
    Write-Host "Running $Pattern (offline)" -ForegroundColor Cyan
    & $python -m unittest discover -s $Directory -p $Pattern -v
    if ($LASTEXITCODE -ne 0) {
        throw "Test suite failed: $Pattern"
    }
}

Invoke-TestSuite "tests/unit" "test_phase13e2_article_url_preparation.py"

if ($IncludeRegressions) {
    Invoke-TestSuite "tests/unit" "test_phase13c1_article_extraction.py"
    Invoke-TestSuite "tests/unit" "test_phase13c2_article_fetch.py"
    Invoke-TestSuite "tests/unit" "test_phase13e1_unified_orchestrator.py"
}

if ($IncludeExtractorSmoke) {
    Invoke-TestSuite "tests/integration" "test_phase13e2_article_url_extractor_smoke.py"
}

Write-Host "Phase 13E.2 selected checks passed. No live HTTP or database writes." -ForegroundColor Green

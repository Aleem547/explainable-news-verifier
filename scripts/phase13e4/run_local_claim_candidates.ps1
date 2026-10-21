param([switch]$IncludeRegressions)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location -LiteralPath $root

$branch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne 'feat/phase13-cross-source') {
    throw 'Refusing to test from another branch. Switch to feat/phase13-cross-source.'
}
$python = Join-Path $root '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Missing .venv/Scripts/python.exe. Activate or restore your existing virtual environment.'
}

function Run-Tests([string]$filename) {
    Write-Host "Running $filename (offline)"
    & $python -m unittest discover -s tests/unit -p $filename -v
    if ($LASTEXITCODE -ne 0) { throw "Tests failed: $filename" }
}

Write-Host 'Phase 13E.4: literal factual-claim candidates. No HTTP, database or AWS operations.'
Run-Tests 'test_phase13e4_claim_candidates.py'

if ($IncludeRegressions) {
    Run-Tests 'test_phase13e3_pasted_article.py'
    Run-Tests 'test_phase13e2_article_url_preparation.py'
    Run-Tests 'test_phase13e1_unified_orchestrator.py'
}

Write-Host 'Phase 13E.4 selected tests passed. No source content stored or published.'

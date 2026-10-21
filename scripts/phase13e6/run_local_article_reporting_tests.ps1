param([switch]$IncludeRegressions)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $repo
$python = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Project .venv Python not found.' }
if ((git branch --show-current).Trim() -ne 'feat/phase13-cross-source') {
    throw 'Wrong Git branch: Phase 13E must run on feat/phase13-cross-source.'
}
$names = @('test_phase13e6_article_reporting.py')
if ($IncludeRegressions) {
    $names += @('test_phase13e5_multi_claim_verification.py',
                'test_phase13e4_claim_candidates.py',
                'test_phase13e3_pasted_article.py',
                'test_phase13e2_article_url_preparation.py',
                'test_phase13e1_unified_orchestrator.py')
}
foreach ($name in $names) {
    Write-Host "Running $name (offline)" -ForegroundColor Cyan
    & $python -m unittest discover -s tests/unit -p $name -v
    if ($LASTEXITCODE -ne 0) { throw "Phase 13E.6 test failed: $name" }
}
Write-Host 'Phase 13E.6 selected tests passed. No HTTP, model, database or AWS operations.' -ForegroundColor Green

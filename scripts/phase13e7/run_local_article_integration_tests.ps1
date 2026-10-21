param([switch]$IncludeRegressions, [switch]$IncludeFrontendTypecheck)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $root
try {
    if ((git branch --show-current).Trim() -ne 'feat/phase13-cross-source') {
        throw 'Wrong branch. Switch to feat/phase13-cross-source.'
    }
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { throw 'Missing project Python .venv.' }
    & $python -m unittest discover -s tests/unit -p 'test_phase13e7_article_integration.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Phase 13E.7 contract tests failed.' }
    & $python -m compileall -q apps/api/routes/article_verification.py apps/api/services/article_api_workflow.py apps/api/main.py
    if ($LASTEXITCODE -ne 0) { throw 'Python syntax validation failed.' }
    if ($IncludeRegressions) {
        foreach ($name in @(
            'test_phase13e6_article_reporting.py',
            'test_phase13e5_multi_claim_verification.py',
            'test_phase13e4_claim_candidates.py',
            'test_phase13e3_pasted_article.py',
            'test_phase13e2_article_url_preparation.py',
            'test_phase13e1_unified_orchestrator.py'
        )) {
            & $python -m unittest discover -s tests/unit -p $name -q
            if ($LASTEXITCODE -ne 0) { throw "Regression failed: $name" }
        }
    }
    if ($IncludeFrontendTypecheck) {
        $tsc = Join-Path $root 'apps\web\node_modules\.bin\tsc.cmd'
        if (-not (Test-Path $tsc)) {
            throw 'TypeScript dependencies missing. Install using the repo lockfile first (do not use npm install without a lockfile).'
        }
        Push-Location (Join-Path $root 'apps\web')
        try {
            & $tsc --noEmit
            if ($LASTEXITCODE -ne 0) { throw 'Frontend TypeScript check failed.' }
        } finally { Pop-Location }
    }
    git diff --check
    if ($LASTEXITCODE -ne 0) { throw 'Git whitespace check failed.' }
    Write-Host 'Phase 13E.7 selected checks passed. No live HTTP, database writes or production changes.' -ForegroundColor Green
} finally { Pop-Location }

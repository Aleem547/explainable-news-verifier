param(
    [switch]$IncludeRegressions,
    [switch]$IncludeFrontendTypecheck,
    [switch]$IncludeLiveGuards
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $root
try {
    if ((git branch --show-current).Trim() -ne 'feat/phase13-cross-source') {
        throw 'Wrong branch: use feat/phase13-cross-source.'
    }
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { throw 'Project Python .venv not found.' }

    Write-Host 'Phase 13E.8: offline release contracts and synthetic model-free pipeline.'
    & $python -m unittest discover -s tests/unit -p 'test_phase13e8_article_release.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Phase 13E.8 offline tests failed.' }
    & $python -m compileall -q tests/unit/test_phase13e8_article_release.py tests/integration/test_phase13e8_local_guards.py
    if ($LASTEXITCODE -ne 0) { throw 'Python syntax validation failed.' }

    if ($IncludeRegressions) {
        foreach ($file in @(
            'test_phase13e7_article_integration.py',
            'test_phase13e6_article_reporting.py',
            'test_phase13e5_multi_claim_verification.py',
            'test_phase13e4_claim_candidates.py',
            'test_phase13e3_pasted_article.py',
            'test_phase13e2_article_url_preparation.py',
            'test_phase13e1_unified_orchestrator.py'
        )) {
            Write-Host "Running regression: $file"
            & $python -m unittest discover -s tests/unit -p $file -q
            if ($LASTEXITCODE -ne 0) { throw "Regression failed: $file" }
        }
    }

    if ($IncludeFrontendTypecheck) {
        $tsc = Join-Path $root 'apps\web\node_modules\.bin\tsc.cmd'
        if (-not (Test-Path $tsc)) { throw 'Frontend TypeScript dependencies are missing.' }
        Push-Location (Join-Path $root 'apps\web')
        try {
            & $tsc --noEmit
            if ($LASTEXITCODE -ne 0) { throw 'Frontend TypeScript check failed.' }
        } finally { Pop-Location }
    }

    if ($IncludeLiveGuards) {
        Write-Host 'Checking only local loopback API and web access without cookies or tokens.'
        Write-Host 'No authenticated inference or database writes will be requested.'
        & $python -m unittest discover -s tests/integration -p 'test_phase13e8_local_guards.py' -v
        if ($LASTEXITCODE -ne 0) { throw 'Loopback-only HTTP guard tests failed.' }
    }

    git diff --check
    if ($LASTEXITCODE -ne 0) { throw 'Git whitespace check failed.' }
    Write-Host 'Phase 13E.8 selected tests passed. No deployment operations performed.' -ForegroundColor Green
} finally {
    Pop-Location
}

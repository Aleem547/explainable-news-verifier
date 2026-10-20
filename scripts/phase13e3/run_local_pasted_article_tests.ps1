param([switch]$IncludeRegressions)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $root
try {
    if ((git branch --show-current) -ne 'feat/phase13-cross-source') {
        throw 'Refusing to run on a different branch.'
    }
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        throw 'Project virtual environment not found. Activate or create .venv first.'
    }

    & $python -m unittest discover -s tests/unit -p 'test_phase13e3_pasted_article.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Phase 13E.3 unit tests failed.' }

    if ($IncludeRegressions) {
        foreach ($pattern in @('test_phase13e1_unified_orchestrator.py', 'test_phase13e2_article_url_preparation.py')) {
            & $python -m unittest discover -s tests/unit -p $pattern -v
            if ($LASTEXITCODE -ne 0) { throw "Regression suite failed: $pattern" }
        }
    }
    Write-Host 'Phase 13E.3 selected offline tests passed. No HTTP, DB, or production operations.' -ForegroundColor Green
} finally {
    Pop-Location
}

param(
    [switch]$IncludeModelSmoke
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Project .venv Python not found.' }
if ((git -C $root branch --show-current).Trim() -ne 'feat/phase13-cross-source') {
    throw 'Expected feat/phase13-cross-source; no work was performed.'
}

Push-Location $root
try {
    Write-Host 'Phase 13D.8 - run ALL Phase 13D offline unit/regression tests.'
    & $python -m unittest discover -s tests/unit -p 'test_phase13d*.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'One or more Phase 13D unit/regression tests failed.' }

    $container = 'explainable-news-verifier-dev-postgres-1'
    $running = @(docker ps --format '{{.Names}}')
    if ($LASTEXITCODE -ne 0 -or $container -notin $running) {
        throw 'Local Docker development PostgreSQL container is not running.'
    }
    $names = @('PHASE13D8_PG_USER', 'PHASE13D8_PG_PASSWORD', 'PHASE13D8_PG_DB', 'PHASE13D8_PG_PORT')
    $old = @{}
    foreach ($name in $names) {
        $old[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    try {
        $env:PHASE13D8_PG_USER = (docker exec $container printenv POSTGRES_USER).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Cannot read local POSTGRES_USER.' }
        $env:PHASE13D8_PG_PASSWORD = (docker exec $container printenv POSTGRES_PASSWORD).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Cannot read local POSTGRES_PASSWORD.' }
        $env:PHASE13D8_PG_DB = (docker exec $container printenv POSTGRES_DB).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Cannot read local POSTGRES_DB.' }
        $env:PHASE13D8_PG_PORT = '5432'
        Write-Host 'Phase 13D.8 - full stored-article pipeline using synthetic data, fake NLI and rollback-only local PostgreSQL.'
        & $python -m unittest discover -s tests/integration -p 'test_phase13d8_full_pipeline_db.py' -v
        if ($LASTEXITCODE -ne 0) { throw 'Phase 13D.8 PostgreSQL full-flow test failed.' }
    }
    finally {
        foreach ($name in $names) {
            [Environment]::SetEnvironmentVariable($name, $old[$name], 'Process')
        }
    }

    if ($IncludeModelSmoke) {
        Write-Host 'Optional: rerun the existing CPU-based frozen model smoke test (may take minutes).'
        & $python -m unittest discover -s tests/integration -p 'test_phase13d5_real_model_smoke.py' -v
        if ($LASTEXITCODE -ne 0) { throw 'The real model smoke test failed.' }
    }

    Write-Host 'Phase 13D.8 selected checks passed. No web requests or AWS operations.'
}
finally { Pop-Location }

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Project .venv Python not found.' }
$container = 'explainable-news-verifier-dev-postgres-1'
if (-not ((docker ps --format '{{.Names}}') -split "`n" -contains $container)) {
    throw 'Local development PostgreSQL container is not running.'
}
$names = @('PHASE13D1_PG_USER','PHASE13D1_PG_PASSWORD','PHASE13D1_PG_DB','PHASE13D1_PG_PORT')
$old = @{}
foreach ($name in $names) { $old[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    $env:PHASE13D1_PG_USER = (docker exec $container printenv POSTGRES_USER).Trim()
    $env:PHASE13D1_PG_PASSWORD = (docker exec $container printenv POSTGRES_PASSWORD).Trim()
    $env:PHASE13D1_PG_DB = (docker exec $container printenv POSTGRES_DB).Trim()
    $env:PHASE13D1_PG_PORT = '5432'
    Write-Host 'Running rollback-only external passage retrieval integration test against 127.0.0.1.'
    Push-Location $root
    try {
        & $python -m unittest discover -s tests/integration -p 'test_phase13d1_external_retrieval_db.py' -v
        if ($LASTEXITCODE -ne 0) { throw 'Phase 13D.1 local DB test failed.' }
    }
    finally { Pop-Location }
}
finally {
    foreach ($name in $names) {
        [Environment]::SetEnvironmentVariable($name, $old[$name], 'Process')
    }
}

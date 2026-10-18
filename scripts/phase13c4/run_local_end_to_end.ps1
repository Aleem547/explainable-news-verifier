# Phase 13C.4. Mocked HTTP + real Trafilatura + rollback-only LOCAL PostgreSQL.
$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if ((git branch --show-current).Trim() -ne 'feat/phase13-cross-source') {
    throw 'Wrong branch: refusing to run outside feat/phase13-cross-source'
}
$pg = 'explainable-news-verifier-dev-postgres-1'
if ((docker inspect --format '{{.State.Running}}' $pg 2>$null) -ne 'true') {
    throw 'Expected local PostgreSQL container is not running'
}
$py = Join-Path (Get-Location).Path '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw 'Local virtual environment not found' }
$previousUrl = [Environment]::GetEnvironmentVariable('DATABASE_URL', 'Process')
$previousFlag = [Environment]::GetEnvironmentVariable('PHASE13C4_LOCAL_DB_TEST', 'Process')
try {
    $pgUser = (docker exec $pg printenv POSTGRES_USER).Trim()
    $pgPass = (docker exec $pg printenv POSTGRES_PASSWORD).Trim()
    $pgDb = (docker exec $pg printenv POSTGRES_DB).Trim()
    if (-not $pgUser -or -not $pgPass -or $pgDb -ne 'verifier') {
        throw 'Development DB credentials unavailable or wrong database name'
    }
    $encUser = [uri]::EscapeDataString($pgUser)
    $encPass = [uri]::EscapeDataString($pgPass)
    $env:DATABASE_URL = 'postgresql+asyncpg://{0}:{1}@127.0.0.1:5432/{2}' -f $encUser, $encPass, $pgDb
    $env:PHASE13C4_LOCAL_DB_TEST = '1'
    Write-Host 'Running local Phase 13C.4 full flow: synthetic HTML, no HTTP, rollback-only DB.'
    & $py -m unittest discover -s tests/integration -p 'test_phase13c4_end_to_end.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Phase 13C.4 end-to-end validation failed' }
} finally {
    if ($null -eq $previousUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }
    else { $env:DATABASE_URL = $previousUrl }
    if ($null -eq $previousFlag) { Remove-Item Env:PHASE13C4_LOCAL_DB_TEST -ErrorAction SilentlyContinue }
    else { $env:PHASE13C4_LOCAL_DB_TEST = $previousFlag }
    $pgPass = $null
}

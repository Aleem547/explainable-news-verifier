# Development PostgreSQL only. NO HTTP request and NO production changes.
$ErrorActionPreference = 'Stop'
if ((git branch --show-current).Trim() -ne 'feat/phase13-cross-source') {
    throw 'Refusing test outside feat/phase13-cross-source'
}
$pg = 'explainable-news-verifier-dev-postgres-1'
if (-not ((docker inspect --format '{{.State.Running}}' $pg 2>$null) -eq 'true')) {
    throw 'Local PostgreSQL container is not running.'
}
$previousUrl = [Environment]::GetEnvironmentVariable('DATABASE_URL', 'Process')
$previousFlag = [Environment]::GetEnvironmentVariable('PHASE13C3_LOCAL_DB_TEST', 'Process')
try {
    $pgUser = (docker exec $pg printenv POSTGRES_USER).Trim()
    $pgPass = (docker exec $pg printenv POSTGRES_PASSWORD).Trim()
    $pgDb = (docker exec $pg printenv POSTGRES_DB).Trim()
    if (-not $pgUser -or -not $pgPass -or $pgDb -ne 'verifier') {
        throw 'Expected nonempty development database credentials and database verifier.'
    }
    $encUser = [uri]::EscapeDataString($pgUser)
    $encPass = [uri]::EscapeDataString($pgPass)
    $env:DATABASE_URL = 'postgresql+asyncpg://{0}:{1}@127.0.0.1:5432/{2}' -f $encUser, $encPass, $pgDb
    $env:PHASE13C3_LOCAL_DB_TEST = '1'
    Write-Host 'Running local synthetic article ingestion/rollback test. No network requests.'
    & .\.venv\Scripts\python.exe -m unittest discover -s tests/integration -p 'test_phase13c3_article_db.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Phase 13C.3 local DB integration test failed.' }
} finally {
    if ($null -eq $previousUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }
    else { $env:DATABASE_URL = $previousUrl }
    if ($null -eq $previousFlag) { Remove-Item Env:PHASE13C3_LOCAL_DB_TEST -ErrorAction SilentlyContinue }
    else { $env:PHASE13C3_LOCAL_DB_TEST = $previousFlag }
    $pgPass = $null
}

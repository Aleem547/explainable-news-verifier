# Run ONLY on your own Windows development machine from the repository root.
# Does not write .env files, print DB passwords, or modify AWS.
$ErrorActionPreference = 'Stop'

if ((git branch --show-current).Trim() -ne 'feat/phase13-cross-source') {
    throw 'Refusing to run outside feat/phase13-cross-source'
}
$pg = 'explainable-news-verifier-dev-postgres-1'
if (-not ((docker inspect --format '{{.State.Running}}' $pg 2>$null) -eq 'true')) {
    throw 'Local PostgreSQL container is not running.'
}

$previousDatabaseUrl = [Environment]::GetEnvironmentVariable('DATABASE_URL', 'Process')
$previousTestFlag = [Environment]::GetEnvironmentVariable('PHASE13B7_LOCAL_DB_TEST', 'Process')
$user = $null
$pass = $null
$db = $null
try {
    $user = (docker exec $pg printenv POSTGRES_USER).Trim()
    $pass = (docker exec $pg printenv POSTGRES_PASSWORD).Trim()
    $db = (docker exec $pg printenv POSTGRES_DB).Trim()
    if (-not $user -or -not $pass -or $db -ne 'verifier') {
        throw 'Expected nonempty dev PostgreSQL credentials and database verifier.'
    }
    $encodedUser = [uri]::EscapeDataString($user)
    $encodedPass = [uri]::EscapeDataString($pass)
    $env:DATABASE_URL = 'postgresql+asyncpg://{0}:{1}@127.0.0.1:5432/{2}' -f $encodedUser, $encodedPass, $db
    $env:PHASE13B7_LOCAL_DB_TEST = '1'

    Write-Host 'Running a local PostgreSQL transaction/rollback test (no HTTP requests).'
    python -m unittest discover -s tests/integration -p 'test_phase13b7_rss_db.py' -v
    if ($LASTEXITCODE -ne 0) { throw 'Phase 13B.7 integration test failed.' }
} finally {
    if ($null -eq $previousDatabaseUrl) {
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    } else { $env:DATABASE_URL = $previousDatabaseUrl }
    if ($null -eq $previousTestFlag) {
        Remove-Item Env:PHASE13B7_LOCAL_DB_TEST -ErrorAction SilentlyContinue
    } else { $env:PHASE13B7_LOCAL_DB_TEST = $previousTestFlag }
    $user = $null
    $pass = $null
    $db = $null
}

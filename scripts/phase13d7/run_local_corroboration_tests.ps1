# Phase 13D.7: offline decision-policy + upstream NLI/agreement regressions.
# Does not access the network, database, model checkpoints or Git remote.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Push-Location $root
try {
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Project .venv Python not found.' }
    $branch = (& git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or $branch -ne 'feat/phase13-cross-source') {
        throw 'Wrong Git branch; expected feat/phase13-cross-source.'
    }
    $patterns = @(
        'test_phase13d7_corroboration_decision.py',
        'test_phase13d6_evidence_agreement.py',
        'test_phase13d5_external_evidence_nli.py'
    )
    foreach ($pattern in $patterns) {
        Write-Host "Running $pattern"
        & $python -m unittest discover -s tests/unit -p $pattern -v
        if ($LASTEXITCODE -ne 0) { throw "Failed: $pattern" }
    }
    Write-Host 'Phase 13D.7 selected offline and regression tests passed.'
}
finally { Pop-Location }

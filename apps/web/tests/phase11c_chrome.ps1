<#
Phase 11C.3 - Chrome launcher for authenticated local benchmarks.

Use from C:\Projects\explainable-news-verifier\apps\web:
    .\tests\phase11c_chrome.ps1 -Mode Login
    .\tests\phase11c_chrome.ps1 -Mode Cleanup
    .\tests\phase11c_chrome.ps1 -Mode Benchmark
    .\tests\phase11c_chrome.ps1 -Mode Status

Login uses normal Chrome with no remote debugging.
Benchmark starts the SAME private Chrome profile with CDP bound to loopback.
Cleanup stops only Chrome processes whose command line contains this
Phase 11C test profile directory. It never removes the profile or cookies.
Never leave the CDP browser open after benchmarking.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Login', 'Cleanup', 'Benchmark', 'Status')]
    [string]$Mode
)

$ErrorActionPreference = 'Stop'
$port = 9237
$profile = Join-Path $env:LOCALAPPDATA 'ExplainableNewsVerifier\Phase11CChromeProfile'
$versionUrl = "http://127.0.0.1:$port/json/version"

function Get-DedicatedChrome {
    @(
        Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" |
            Where-Object {
                $_.CommandLine -and
                $_.CommandLine.IndexOf(
                    $profile,
                    [System.StringComparison]::OrdinalIgnoreCase
                ) -ge 0
            }
    )
}

function Get-CdpVersion {
    try {
        $response = Invoke-RestMethod -Uri $versionUrl -TimeoutSec 2 -ErrorAction Stop
        if ($response.Browser -and $response.webSocketDebuggerUrl) {
            return $response
        }
    } catch {
        # The endpoint is not ready (or the port is not listening).
    }
    return $null
}

function Find-Chrome {
    $candidates = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    throw 'Google Chrome could not be found in the standard Windows install paths.'
}

if ($Mode -eq 'Status') {
    $owners = @(Get-DedicatedChrome)
    $cdp = Get-CdpVersion
    Write-Host "Dedicated Chrome processes: $($owners.Count)"
    if ($owners.Count) {
        Write-Host "Dedicated PIDs: $(($owners | ForEach-Object ProcessId) -join ', ')"
    }
    if ($cdp) {
        Write-Host "CDP available at 127.0.0.1:$port ($($cdp.Browser))" -ForegroundColor Green
    } else {
        Write-Host "CDP unavailable at 127.0.0.1:$port" -ForegroundColor Yellow
    }
    exit 0
}

if ($Mode -eq 'Cleanup') {
    $owners = @(Get-DedicatedChrome)
    if (-not $owners.Count) {
        Write-Host 'No Chrome process using the Phase 11C profile was found.' -ForegroundColor Green
        exit 0
    }

    Write-Host 'Closing ONLY Chrome processes launched with the Phase 11C test profile.' -ForegroundColor Yellow
    foreach ($owner in $owners) {
        Write-Host "Stopping dedicated Chrome PID $($owner.ProcessId)"
        & taskkill.exe /PID $owner.ProcessId /T /F | Out-Null
    }
    Start-Sleep -Seconds 2
    $left = @(Get-DedicatedChrome)
    if ($left.Count) {
        throw "Some dedicated Chrome processes remain: $(($left | ForEach-Object ProcessId) -join ', '). Close those windows and try again."
    }
    Write-Host 'Dedicated Chrome closed. Test profile and login cookies preserved.' -ForegroundColor Green
    exit 0
}

$chrome = Find-Chrome
New-Item -ItemType Directory -Path $profile -Force | Out-Null

# Do not let Chrome silently reuse a still-running process: in that case
# additional command-line arguments (including CDP flags) are ignored.
$owners = @(Get-DedicatedChrome)
if ($owners.Count) {
    throw "The dedicated test Chrome profile is still running (PID(s): $(($owners | ForEach-Object ProcessId) -join ', ')). Close its window, or run .\tests\phase11c_chrome.ps1 -Mode Cleanup, then retry."
}

$arguments = @(
    ('--user-data-dir="' + $profile + '"'),
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-mode',
    '--new-window'
)

if ($Mode -eq 'Login') {
    Write-Host 'Opening ordinary Chrome with the dedicated Phase 11C profile.' -ForegroundColor Cyan
    Write-Host 'Sign in on /account and confirm success. Do not click Sign out.'
    Write-Host 'Then CLOSE this dedicated Chrome window completely.'
    $arguments += 'http://localhost:3000/account'
    Start-Process -FilePath $chrome -ArgumentList $arguments | Out-Null
    exit 0
}

# Never accidentally attach the benchmark to a different browser.
if (Get-CdpVersion) {
    throw "Port $port already has a CDP endpoint. Close that debug browser before continuing."
}

Write-Host 'Starting the dedicated Chrome profile with LOCAL-ONLY CDP.' -ForegroundColor Cyan
$arguments += @(
    "--remote-debugging-port=$port",
    '--remote-debugging-address=127.0.0.1',
    'http://localhost:3000/verify'
)
$started = Start-Process -FilePath $chrome -ArgumentList $arguments -PassThru
Write-Host "Chrome launch PID: $($started.Id)"

# Poll instead of assuming Chrome is ready after a fixed 3-second delay.
$cdp = $null
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    $cdp = Get-CdpVersion
    if ($cdp) { break }
}

if (-not $cdp) {
    $running = @(Get-DedicatedChrome)
    Write-Host "Dedicated Chrome processes found: $($running.Count)"
    throw "Chrome did not open CDP on 127.0.0.1:$port after 20 seconds. Run -Mode Status, then -Mode Cleanup. If still blocked, check Chrome policies or installation. Do not run the browser benchmark yet."
}

Write-Host "Chrome debugging READY on 127.0.0.1:$port ($($cdp.Browser))" -ForegroundColor Green
Write-Host 'Keep this Chrome window OPEN. In another PowerShell terminal, run:'
Write-Host '  node .\tests\phase11c_browser_benchmark.mjs --runs 1' -ForegroundColor Cyan
Write-Host 'When finished, run .\tests\phase11c_chrome.ps1 -Mode Cleanup.'

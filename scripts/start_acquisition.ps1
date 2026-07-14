# Start a detached acquisition process on Windows.
# This process survives terminal/Cursor closure.

param(
    [string[]]$Pairs = @("EURUSD", "GBPUSD", "USDJPY"),
    [string]$Start = "2019-01-01",
    [string]$End = "2019-12-31",
    [int]$Workers = 2,
    [string]$StateDir = "data\acquisition_state",
    [string]$RawDir = "data\raw\dukascopy-node",
    [string]$LogDir = "logs\acquisition",
    [switch]$RetryFailed,
    [switch]$RepairMissing
)

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PidFile = Join-Path $RepoRoot (Join-Path $StateDir "runner.pid")

if (Test-Path $PidFile) {
    $existingPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    try {
        Get-Process -Id $existingPid -ErrorAction Stop | Out-Null
        Write-Host "ERROR: Runner already active (PID $existingPid)" -ForegroundColor Red
        exit 1
    } catch {
        Remove-Item $PidFile -ErrorAction SilentlyContinue
    }
}

$PythonExe = (Get-Command python -ErrorAction Stop).Source
$ScriptPath = Join-Path $RepoRoot "scripts\run_persistent_acquisition.py"

$pairsArg = ($Pairs -join " ")
$arguments = @(
    $ScriptPath,
    "--pairs", $pairsArg,
    "--start", $Start,
    "--end", $End,
    "--workers", $Workers,
    "--resume",
    "--state-dir", (Join-Path $RepoRoot $StateDir),
    "--raw-dir", (Join-Path $RepoRoot $RawDir),
    "--log-dir", (Join-Path $RepoRoot $LogDir)
)

if ($RetryFailed) { $arguments += "--retry-failed" }
if ($RepairMissing) { $arguments += "--repair-missing" }

$logDir = Join-Path $RepoRoot $LogDir
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$stdoutLog = Join-Path $logDir "stdout_$ts.log"
$stderrLog = Join-Path $logDir "stderr_$ts.log"

$proc = Start-Process -FilePath $PythonExe `
    -ArgumentList $arguments `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -WindowStyle Hidden `
    -PassThru

Write-Host "Acquisition started:" -ForegroundColor Green
Write-Host "  PID: $($proc.Id)"
Write-Host "  Stdout: $stdoutLog"
Write-Host "  Stderr: $stderrLog"
Write-Host "  Workers: $Workers"
Write-Host ""
Write-Host "Check status:"
Write-Host "  .\scripts\status_acquisition.ps1"

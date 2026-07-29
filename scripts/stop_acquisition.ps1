# Gracefully stop the acquisition runner on Windows.

param(
    [string]$StateDir = "data\acquisition_state"
)

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PidFile = Join-Path $RepoRoot (Join-Path $StateDir "runner.pid")

if (-not (Test-Path $PidFile)) {
    Write-Host "No PID file found - runner may not be active." -ForegroundColor Yellow
    exit 0
}

$RunnerPid = Get-Content $PidFile
try {
    $proc = Get-Process -Id $RunnerPid -ErrorAction Stop
    Write-Host "Sending stop signal to PID $RunnerPid..." -ForegroundColor Yellow
    Stop-Process -Id $RunnerPid -ErrorAction Stop
    Write-Host "Signal sent. Runner will finish current atomic operation." -ForegroundColor Green
} catch {
    Write-Host "Process $RunnerPid not found - cleaning up stale PID file." -ForegroundColor Yellow
    Remove-Item $PidFile -ErrorAction SilentlyContinue
}

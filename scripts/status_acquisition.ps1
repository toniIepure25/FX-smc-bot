# Check acquisition runner status on Windows.

param(
    [string]$StateDir = "data\acquisition_state"
)

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PythonExe = (Get-Command python -ErrorAction Stop).Source
$ScriptPath = Join-Path $RepoRoot "scripts\run_persistent_acquisition.py"
$FullStateDir = Join-Path $RepoRoot $StateDir

& $PythonExe $ScriptPath --status --state-dir $FullStateDir

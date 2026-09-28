# PowerShell helper script to execute AION Agent Smoke Tests directly from CLI
param (
    [string]$Test = "",
    [string]$Config = "evals/agent_smoke_tests/test_config.json"
)

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $RepoRoot

$ArgsList = @("evals/agent_smoke_tests/test_runner.py")
if ($Test -ne "") {
    $ArgsList += "--test"
    $ArgsList += $Test
}
if ($Config -ne "") {
    $ArgsList += "--config"
    $ArgsList += $Config
}

$PythonCmd = "python"
if (Test-Path "$RepoRoot\.venv\Scripts\python.exe") {
    $PythonCmd = "$RepoRoot\.venv\Scripts\python.exe"
}

Write-Host "Avvio AION Agent Smoke Tests con $PythonCmd..." -ForegroundColor Cyan
& $PythonCmd @ArgsList

#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Core = Join-Path $Root "scripts/upgrade_core.py"
if (-not (Test-Path $Core)) {
  Write-Host "Missing $Core" -ForegroundColor Red
  exit 2
}

function Banner {
  Write-Host ""
  Write-Host @"
╔════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                    ║
║                                                                                    ║
║                                                                                    ║
║                                                                                    ║
║    █████╗ ██╗ ██████╗ ███╗   ██╗     █████╗  ██████╗ ███████╗███╗   ██╗████████╗   ║
║   ██╔══██╗██║██╔═══██╗████╗  ██║    ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝   ║
║   ███████║██║██║   ██║██╔██╗ ██║    ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║      ║
║   ██╔══██║██║██║   ██║██║╚██╗██║    ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║      ║
║   ██║  ██║██║╚██████╔╝██║ ╚████║    ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║      ║
║   ╚═╝  ╚═╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝    ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝      ║
║                                                                                    ║
║                         ·  u p g r a d e   s c r i p t  ·                          ║
║                                                                                    ║
║                                                                                    ║
╚════════════════════════════════════════════════════════════════════════════════════╝
"@ -ForegroundColor Red
  Write-Host ""
}

function Find-Python {
  foreach ($cmd in @("python", "py")) {
    try {
      $null = Get-Command $cmd -ErrorAction Stop
      return $cmd
    } catch {}
  }
  throw "Python non trovato. Installa Python 3."
}

$dryRun = $false
$dockerMode = $false
foreach ($a in $args) {
  if ($a -eq "--dry-run") { $dryRun = $true }
  if ($a -eq "--docker")  { $dockerMode = $true }
}

$extra = @()
# Skip venv prep in Docker mode (no local virtualenv needed)
if ((-not $dryRun) -and (-not $dockerMode)) { $extra += "--prepare-runtime" }

Banner
if ($dockerMode) {
  Write-Host "[upgrade] Docker compose mode - will rebuild images + restart services." -ForegroundColor Cyan
}
$py = Find-Python
& $py $Core @extra @args
exit $LASTEXITCODE

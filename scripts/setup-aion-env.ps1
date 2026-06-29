#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Core = Join-Path $Root "scripts/setup_core.py"
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
║                           ·  e n v   s e t u p  ·                                  ║
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
$forwarded = @()
foreach ($a in $args) {
  switch ($a) {
    "--dry-run" { $dryRun = $true }
    "--docker"  { $dockerMode = $true }
    default     { $forwarded += $a }
  }
}

if ($dockerMode) {
  Banner
  Write-Host "[setup] Docker preset selected." -ForegroundColor Cyan
  $envFile = Join-Path $Root ".env"
  $template = Join-Path $Root ".env.docker.example"
  if (-not (Test-Path $template)) {
    Write-Host "Missing $template" -ForegroundColor Red
    exit 2
  }
  if ((Test-Path $envFile) -and (-not $dryRun)) {
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $bak = "$envFile.bak.$ts"
    Copy-Item $envFile $bak
    Write-Host "[setup] Backup created: $bak"
  }
  if (-not $dryRun) {
    Copy-Item $template $envFile -Force
    Write-Host "[setup] Copied .env.docker.example -> .env (edit DOMAIN, CADDY_* ports, AION_API_URL, secrets)"
  } else {
    Write-Host "[dry-run] Would copy .env.docker.example -> .env"
  }
  Write-Host ""
  Write-Host "Next steps:"
  Write-Host "  notepad .env                                # DOMAIN, CADDY_HTTP_PORT/CADDY_HTTPS_PORT (if 80/443 busy), secrets"
  Write-Host "  docker compose up -d --build                # full prod stack"
  Write-Host "  docker compose -f docker-compose.dev.yml up # dev essentials only"
  exit 0
}

$extra = @()
if (-not $dryRun) { $extra += "--prepare-runtime" }
if ($dryRun)     { $forwarded += "--dry-run" }

Banner
$py = Find-Python
& $py $Core @extra @forwarded
exit $LASTEXITCODE

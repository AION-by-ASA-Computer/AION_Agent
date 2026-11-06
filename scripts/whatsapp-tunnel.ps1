<#
.SYNOPSIS
  Tunnel Cloudflare temporaneo + stack Docker, per collegare WhatsApp e Telegram
  (modalità webhook) senza un dominio. Versione Windows di scripts/whatsapp-tunnel.sh.

.DESCRIPTION
  1. apre un quick tunnel (https://<random>.trycloudflare.com) verso Caddy sulla porta HTTP locale;
  2. genera un override compose che punta gli URL pubblici del backend al tunnel
     (AION_PUBLIC_API_URL, AION_OAUTH_REDIRECT_BASE_URL, AION_PUBLIC_CHAT_URL,
     AION_CHAT_URL) senza toccare .env;
  3. esegue `docker compose up -d --build`;
  4. stampa l'URL di callback per Meta e resta in primo piano: Ctrl+C chiude il tunnel.

  L'URL del tunnel cambia a ogni avvio: va reinserito su Meta (Webhook -> Callback URL).
  Telegram invece non richiede passaggi manuali: con "Ricezione update = Webhook" in
  Admin -> Telegram il backend registra da solo il webhook (setWebhook) all'avvio,
  usando AION_PUBLIC_API_URL, quindi segue l'URL nuovo a ogni ricreazione del container.

  Compatibile con Windows PowerShell 5.1 e PowerShell 7. Il file è salvato in UTF-8
  con BOM: senza BOM PowerShell 5.1 lo leggerebbe come ANSI e rovinerebbe le lettere accentate.

.PARAMETER NoBuild
  docker compose up -d senza --build.

.PARAMETER Port
  Porta HTTP locale di Caddy (default: CADDY_HTTP_PORT da .env, altrimenti 80).

.PARAMETER DownOnExit
  All'uscita esegue anche docker compose down.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\whatsapp-tunnel.ps1
  powershell -ExecutionPolicy Bypass -File scripts\whatsapp-tunnel.ps1 -NoBuild -Port 8080
#>
[CmdletBinding()]
param(
  [switch]$NoBuild,
  [int]$Port = 0,
  [switch]$DownOnExit
)

$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$StateDir = Join-Path $Root '.aion-tunnel'
# cloudflared scrive i suoi log (URL del tunnel compreso) su stderr; Start-Process
# vuole due file diversi per stdout e stderr.
$LogFile = Join-Path $StateDir 'cloudflared.log'
$OutFile = Join-Path $StateDir 'cloudflared.out.log'
$OverrideFile = Join-Path $StateDir 'docker-compose.tunnel.yml'
$EnvFile = Join-Path $Root '.env'

function Die([string]$Message) {
  Write-Host "ERRORE: $Message" -ForegroundColor Red
  exit 1
}

<#
  Runs a native command and returns its exit code, without letting its stderr turn
  into a terminating error: in Windows PowerShell 5.1 redirected stderr of a native
  exe becomes ErrorRecords, which $ErrorActionPreference = 'Stop' would throw on.
  The command output goes to the console (Out-Host), so the only value returned
  is the exit code.
#>
function Invoke-Native([scriptblock]$Command) {
  $previous = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    & $Command | Out-Host
    return $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $previous
  }
}

<#
  Reads one key from .env without executing it (the bash version avoids `source`
  for the same reason): last occurrence wins, trailing comments and quotes stripped.
#>
function Get-EnvValue([string]$Key) {
  $value = $null
  foreach ($line in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
    if ($line -match "^\s*$([regex]::Escape($Key))=(.*)$") {
      $value = ($Matches[1] -replace '\s*#.*$', '').Trim().Trim('"', "'")
    }
  }
  return $value
}

# --- Prerequisites ---
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
  Die "cloudflared non trovato. Windows: winget install --id Cloudflare.cloudflared (poi riapri il terminale)"
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Die "docker non trovato" }
if ((Invoke-Native { docker info *> $null }) -ne 0) {
  Die "il demone Docker non risponde (Docker Desktop è avviato?)"
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
  Die "manca $EnvFile (copy .env.docker.example .env oppure copy .env.example .env)"
}

# --- Local Caddy port: -Port, else CADDY_HTTP_PORT from .env, else 80 ---
if ($Port -le 0) {
  $fromEnv = Get-EnvValue 'CADDY_HTTP_PORT'
  if ([string]::IsNullOrWhiteSpace($fromEnv)) { $Port = 80 }
  elseif ($fromEnv -match '^\d+$') { $Port = [int]$fromEnv }
  else { Die "porta non valida in .env: CADDY_HTTP_PORT=$fromEnv" }
}

# A real DOMAIN makes Caddy answer only for that host: the tunnel host would get 404.
$domain = Get-EnvValue 'DOMAIN'
if ($domain -and -not $domain.StartsWith(':')) {
  Write-Host "ATTENZIONE: DOMAIN=$domain nel .env. Caddy risponde solo a quell'host e il tunnel riceverà 404." -ForegroundColor Yellow
  Write-Host "            Per il tunnel usa DOMAIN=:80 (modalità HTTP locale)." -ForegroundColor Yellow
}

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
Set-Content -LiteralPath $LogFile -Value '' -Encoding UTF8
Set-Content -LiteralPath $OutFile -Value '' -Encoding UTF8

# `-f` disables the automatic loading of the local override: include it ourselves.
$composeFiles = @('-f', (Join-Path $Root 'docker-compose.yml'))
$localOverride = Join-Path $Root 'docker-compose.override.yml'
if (Test-Path -LiteralPath $localOverride) { $composeFiles += @('-f', $localOverride) }

$cf = $null
$stackUp = $false

# try/finally instead of the bash traps: PowerShell runs `finally` also on Ctrl+C,
# so the tunnel is always closed.
try {
  Write-Host "Avvio il tunnel Cloudflare verso http://localhost:$Port ..."
  $cf = Start-Process -FilePath 'cloudflared' `
    -ArgumentList @('tunnel', '--no-autoupdate', '--url', "http://localhost:$Port") `
    -RedirectStandardError $LogFile -RedirectStandardOutput $OutFile `
    -NoNewWindow -PassThru

  # Wait up to 60s for the trycloudflare URL to appear in the log.
  $tunnelUrl = $null
  for ($i = 0; $i -lt 60 -and -not $tunnelUrl; $i++) {
    if ($cf.HasExited) {
      $tail = (Get-Content -LiteralPath $LogFile -Tail 20 -ErrorAction SilentlyContinue) -join "`n"
      Die "cloudflared si è chiuso. Log: $LogFile`n$tail"
    }
    # The log is still open for writing by cloudflared: read it with a shared handle.
    $text = ''
    try {
      $fs = [System.IO.File]::Open($LogFile, 'Open', 'Read', 'ReadWrite')
      try { $text = (New-Object System.IO.StreamReader($fs)).ReadToEnd() } finally { $fs.Dispose() }
    } catch { $text = '' }
    $m = [regex]::Match($text, 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($m.Success) { $tunnelUrl = $m.Value } else { Start-Sleep -Seconds 1 }
  }
  if (-not $tunnelUrl) { Die "nessun URL dal tunnel dopo 60s. Log: $LogFile" }
  Write-Host "Tunnel: $tunnelUrl" -ForegroundColor Green

  # Compose override with the public URLs pointed at the tunnel (UTF-8 without BOM).
  $override = @"
# Generato da scripts/whatsapp-tunnel.ps1: non modificare, viene riscritto a ogni avvio.
services:
  backend:
    environment:
      AION_PUBLIC_API_URL: "$tunnelUrl/api"
      # Va sovrascritto anche questo: _public_api_base_url() (usato per gli URL dei
      # webhook WhatsApp e Telegram) lo legge PRIMA di AION_PUBLIC_API_URL, e il compose
      # lo deriva dal .env (es. http://localhost:8001) se non è impostato esplicitamente.
      AION_OAUTH_REDIRECT_BASE_URL: "$tunnelUrl/api"
      AION_PUBLIC_CHAT_URL: "$tunnelUrl"
      AION_CHAT_URL: "$tunnelUrl"
"@
  [System.IO.File]::WriteAllText($OverrideFile, $override, (New-Object System.Text.UTF8Encoding($false)))

  $upArgs = @('up', '-d')
  if (-not $NoBuild) { $upArgs += '--build' }
  Write-Host "docker compose $($upArgs -join ' ') ..."
  Push-Location $Root
  try {
    $code = Invoke-Native { docker compose @composeFiles -f $OverrideFile @upArgs }
  } finally {
    Pop-Location
  }
  if ($code -ne 0) { Die "docker compose up non riuscito (exit $code)" }
  $stackUp = $true

  # The trycloudflare subdomain DNS can take a few seconds to propagate.
  Write-Host "Attendo che il backend risponda attraverso il tunnel..."
  $healthy = $false
  for ($i = 0; $i -lt 60 -and -not $healthy; $i++) {
    try {
      $r = Invoke-WebRequest -Uri "$tunnelUrl/api/health" -UseBasicParsing -TimeoutSec 5
      if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) { $healthy = $true }
    } catch {
      Start-Sleep -Seconds 3
    }
  }

  $line = '-' * 68
  Write-Host @"

$line
 Callback URL per Meta (App -> WhatsApp -> Configurazione -> Webhook):

   $tunnelUrl/api/v1/channels/whatsapp/webhook

 Verify token: admin-ui -> WhatsApp (http://localhost:$Port/admin/whatsapp)
 Poi su Meta: "Verifica e salva" e sottoscrivi il campo "messages".

 Telegram (webhook): admin-ui -> Telegram (http://localhost:$Port/admin/telegram)
 -> Connessione -> "Ricezione degli update" = Webhook, poi Salva. Il backend registra
 da solo su Telegram, per il manager e per ogni assistente:

   $tunnelUrl/api/v1/channels/telegram/webhook/<bot id>

 Lo stato (URL registrato, update in coda, ultimo errore) è nel riquadro Stato.

 Chat-ui pubblica: $tunnelUrl
 Log del tunnel:   $LogFile
$line
"@
  if (-not $healthy) {
    Write-Host "ATTENZIONE: $tunnelUrl/api/health non risponde ancora. Controlla: docker compose ps / logs backend caddy" -ForegroundColor Yellow
  }
  Write-Host "Tunnel attivo. Ctrl+C per chiuderlo." -ForegroundColor Green

  # Short waits instead of a blocking WaitForExit(), so Ctrl+C is handled promptly.
  while (-not $cf.HasExited) { Start-Sleep -Milliseconds 500 }
  Write-Host "cloudflared terminato. Log: $LogFile"
} finally {
  Write-Host ''
  if ($cf -and -not $cf.HasExited) {
    Write-Host "Chiudo il tunnel (pid $($cf.Id))..."
    try { Stop-Process -Id $cf.Id -Force -ErrorAction Stop } catch {}
  }
  if ($DownOnExit) {
    Write-Host "docker compose down..."
    Push-Location $Root
    try { Invoke-Native { docker compose @composeFiles -f $OverrideFile down } | Out-Null } finally { Pop-Location }
  } elseif ($stackUp) {
    Write-Host "Lo stack resta avviato con gli URL del tunnel ormai chiuso."
    Write-Host "Per tornare agli URL del .env: docker compose up -d backend"
  }
}

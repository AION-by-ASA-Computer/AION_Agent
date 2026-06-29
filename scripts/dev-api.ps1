# scripts/dev-api.ps1
# Script di sviluppo per avviare il backend Python in ambiente Windows.

$ErrorActionPreference = "Stop"

# Trova la cartella root del progetto
$SCRIPT_DIR = $PSScriptRoot
$ROOT = Split-Path -Path $SCRIPT_DIR -Parent
$VENV_DIR = Join-Path -Path $ROOT -ChildPath ".venv"
$REQ_FILE = Join-Path -Path $ROOT -ChildPath "requirements.txt"

# Cerca l'eseguibile Python
$PYTHON_BIN = "python"
if (-not (Get-Command $PYTHON_BIN -ErrorAction SilentlyContinue)) {
    Write-Error "[AION] Python non trovato nel PATH. Installa Python prima di continuare."
    exit 1
}

# Verifica e creazione del virtualenv
if (-not (Test-Path -Path $VENV_DIR)) {
    Write-Host "[AION] Creo virtualenv in $VENV_DIR" -ForegroundColor Cyan
    & $PYTHON_BIN -m venv $VENV_DIR
    
    # Attiva il virtualenv
    $ActivateScript = Join-Path -Path $VENV_DIR -ChildPath "Scripts\Activate.ps1"
    & $ActivateScript
    
    Write-Host "[AION] Aggiorno pip e installo dipendenze" -ForegroundColor Cyan
    python -m pip install --upgrade pip
    
    if (Test-Path -Path $REQ_FILE) {
        python -m pip install -r $REQ_FILE
    } else {
        Write-Warning "[AION] $REQ_FILE non trovato, skip install dipendenze"
    }
} else {
    # Attiva il virtualenv esistente
    $ActivateScript = Join-Path -Path $VENV_DIR -ChildPath "Scripts\Activate.ps1"
    & $ActivateScript
}

# Spostati nella cartella root
Set-Location -Path $ROOT

$VenvPrefix = python -c "import sys; print(sys.prefix)"
Write-Host "[AION] venv attivo: $VenvPrefix" -ForegroundColor Green
Write-Host "[AION] Avvio API dev con --reload (watch: src, config, .env*)" -ForegroundColor Cyan

# Carica host e porta da variabili d'ambiente o usa i fallback
$ApiHost = if ($env:AION_API_HOST) { $env:AION_API_HOST } else { "0.0.0.0" }
$ApiPort = if ($env:AION_API_PORT) { $env:AION_API_PORT } else { "8001" }

# Esegui uvicorn
uvicorn src.api.main:app `
  --host $ApiHost `
  --port $ApiPort `
  --reload `
  --reload-dir src `
  --reload-dir config `
  --reload-include ".env" `
  --reload-include ".env.local"

#!/usr/bin/env bash
# ==============================================================================
# AION Local CI runner
# ==============================================================================
# Questo script replica localmente i controlli eseguiti dalla pipeline CI
# di GitHub Actions (.github/workflows/ci.yml) sul runner aion-ci-worker.
# ==============================================================================

set -eo pipefail

# Colori per output leggibile
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0;60m' # No Color
RESET='\033[0m'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

log_info() {
  echo -e "${BLUE}[INFO]${RESET} $1"
}

log_success() {
  echo -e "${GREEN}[PASS]${RESET} $1"
}

log_warn() {
  echo -e "${YELLOW}[WARN]${RESET} $1"
}

log_error() {
  echo -e "${RED}[FAIL]${RESET} $1"
}

FAILED_STEPS=()

# ------------------------------------------------------------------------------
# Fase 1: Setup e Sincronizzazione Ambiente
# ------------------------------------------------------------------------------
echo -e "\n=== 1. SETUP & CONFIG SYNC ==="
log_info "Esecuzione dello script di setup standard in modalità non interattiva..."
if python3 scripts/setup_core.py --non-interactive; then
  log_success "Sincronizzazione di /config e /mcp_servers completata."
else
  log_error "Errore durante setup_core.py"
  FAILED_STEPS+=("Setup & Sincronizzazione")
fi

# ------------------------------------------------------------------------------
# Fase 2: Backend Checks (Ruff, Pytest)
# ------------------------------------------------------------------------------
echo -e "\n=== 2. BACKEND CHECKS ==="

# Verifica se il virtualenv esiste
if [[ -d ".venv" ]]; then
  PYTHON_BIN=".venv/bin/python"
  PYTEST_BIN=".venv/bin/pytest"
else
  PYTHON_BIN="python3"
  PYTEST_BIN="pytest"
fi

# Esegui Ruff per linting e formattazione
log_info "Esecuzione ruff check e format..."
if ! command -v ruff &> /dev/null && ! [[ -f ".venv/bin/ruff" ]]; then
  log_warn "Ruff non trovato. Installazione temporanea nel venv..."
  $PYTHON_BIN -m pip install ruff --quiet
fi

RUFF_BIN="ruff"
if [[ -f ".venv/bin/ruff" ]]; then
  RUFF_BIN=".venv/bin/ruff"
fi

if $RUFF_BIN check --config "$ROOT/ruff.toml" src/; then
  $RUFF_BIN format --check --config "$ROOT/ruff.toml" src/ || log_warn "Alcuni file necessitano di essere formattati con ruff (non bloccante)."
  log_success "Linting Python superato."
else
  log_error "Ruff ha rilevato errori strutturali o di sintassi bloccanti."
  FAILED_STEPS+=("Python Linting (Ruff)")
fi

# Esegui i test unitari ed endpoint
log_info "Esecuzione dei test degli endpoint API..."
export AION_CHAT_PASSWORD_AUTH="0"
export AION_ADMIN_PASSWORD_AUTH="0"
export AION_REDIS_FALLBACK_LOCAL="1"
unset AION_REDIS_URL

if $PYTEST_BIN src/test/test_api_endpoints.py -v; then
  log_success "Suite di test API superata con successo."
else
  log_error "Alcuni test degli endpoint API sono falliti."
  FAILED_STEPS+=("Backend API Tests")
fi

# ------------------------------------------------------------------------------
# Fase 3: Frontend Checks (Monorepo pnpm compilation)
# ------------------------------------------------------------------------------
echo -e "\n=== 3. FRONTEND BUILD CHECKS ==="

if ! command -v pnpm &> /dev/null; then
  log_error "pnpm non trovato nel sistema. Impossibile compilare le UI JS."
  FAILED_STEPS+=("Frontend Compilations (pnpm missing)")
else
  log_info "Installazione delle dipendenze monorepo con pnpm..."
  if pnpm install --no-frozen-lockfile; then
    
    # 1. Chat-UI
    log_info "Compilazione di chat-ui..."
    if (cd chat-ui && pnpm build); then
      log_success "chat-ui compilato correttamente."
    else
      log_error "Errore nella compilazione di chat-ui."
      FAILED_STEPS+=("chat-ui build")
    fi

    # 2. Admin-UI
    log_info "Compilazione di admin-ui..."
    if (cd admin-ui && pnpm build); then
      log_success "admin-ui compilato correttamente."
    else
      log_error "Errore nella compilazione di admin-ui."
      FAILED_STEPS+=("admin-ui build")
    fi

    # 3. Docusaurus Website
    log_info "Compilazione di website (Docusaurus)..."
    if (cd website && pnpm build); then
      log_success "website compilato correttamente."
    else
      log_error "Errore nella compilazione della documentazione Docusaurus."
      FAILED_STEPS+=("website build")
    fi

  else
    log_error "pnpm install fallito."
    FAILED_STEPS+=("pnpm dependency installation")
  fi
fi

# ------------------------------------------------------------------------------
# Fase 4: Docker Build Checks (Opzionali se Docker non è attivo)
# ------------------------------------------------------------------------------
echo -e "\n=== 4. DOCKER BUILD CHECKS ==="

if ! command -v docker &> /dev/null; then
  log_warn "Docker non installato. Salto i controlli di build dei container."
elif ! docker info &> /dev/null; then
  log_warn "Il demone Docker non sembra attivo. Salto i controlli di build dei container."
else
  log_info "Avvio build di test dei 4 container Docker monorepo..."
  
  # 1. Backend
  if docker build -f docker/Dockerfile.backend -t aion-backend:ci-test . --quiet; then
    log_success "Dockerfile.backend compilato correttamente."
  else
    log_error "Errore nella build di Dockerfile.backend."
    FAILED_STEPS+=("Docker Backend Build")
  fi

  # 2. Chat UI
  if docker build -f docker/Dockerfile.chat-ui -t aion-chat-ui:ci-test . --quiet; then
    log_success "Dockerfile.chat-ui compilato correttamente."
  else
    log_error "Errore nella build di Dockerfile.chat-ui."
    FAILED_STEPS+=("Docker Chat-UI Build")
  fi

  # 3. Admin UI
  if docker build -f docker/Dockerfile.admin-ui -t aion-admin-ui:ci-test . --quiet; then
    log_success "Dockerfile.admin-ui compilato correttamente."
  else
    log_error "Errore nella build di Dockerfile.admin-ui."
    FAILED_STEPS+=("Docker Admin-UI Build")
  fi

  # 4. Docusaurus Website
  if docker build -f docker/Dockerfile.website -t aion-website:ci-test . --quiet; then
    log_success "Dockerfile.website compilato correttamente."
  else
    log_error "Errore nella build di Dockerfile.website."
    FAILED_STEPS+=("Docker Website Build")
  fi
fi

# ------------------------------------------------------------------------------
# Riassunto Finale
# ------------------------------------------------------------------------------
echo -e "\n=============================================================================="
if [[ ${#FAILED_STEPS[@]} -eq 0 ]]; then
  echo -e "${GREEN}✓ TUTTI I CONTROLLI LOCAL-CI SONO STATI SUPERATI CON SUCCESSO!${RESET}"
  echo -e "=============================================================================="
  exit 0
else
  echo -e "${RED}✗ ALCUNI CONTROLLI LOCAL-CI SONO FALLITI!${RESET}"
  echo -e "Step falliti:"
  for step in "${FAILED_STEPS[@]}"; do
    echo -e "  - ${RED}${step}${RESET}"
  done
  echo -e "=============================================================================="
  exit 1
fi

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT/.venv"
REQ_FILE="$ROOT/requirements.txt"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "[AION] Python non trovato. Installa Python 3 prima di continuare." >&2
  exit 1
fi

_ensure_venv() {
  if [[ -f "$ROOT/scripts/uv_runtime.py" ]]; then
    echo "[AION] Preparo .venv (uv se disponibile, altrimenti pip)"
    "$PYTHON_BIN" "$ROOT/scripts/uv_runtime.py"
    return
  fi
  echo "[AION] Creo virtualenv in $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  echo "[AION] Aggiorno pip e installo requirements"
  python -m pip install --upgrade pip
  if [[ -f "$REQ_FILE" ]]; then
    python -m pip install -r "$REQ_FILE"
  else
    echo "[AION] WARNING: $REQ_FILE non trovato, skip install dipendenze"
  fi
}

if [[ ! -d "$VENV_DIR" ]]; then
  _ensure_venv
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

cd "$ROOT"
if [[ ! -f "$ROOT/mcp_servers/agent_db/db_manager.py" ]] && [[ -f "$ROOT/scripts/sync_mcp_servers.py" ]]; then
  echo "[AION] mcp_servers/ incompleta — sync da mcp_servers_std/"
  python "$ROOT/scripts/sync_mcp_servers.py"
fi
echo "[AION] venv attivo: $(python -c 'import sys; print(sys.prefix)')"
echo "[AION] Avvio API dev con --reload (watch: src, config, .env*)"

exec uvicorn src.api.main:app \
  --host "${AION_API_HOST:-0.0.0.0}" \
  --port "${AION_API_PORT:-8001}" \
  --reload \
  --reload-dir src \
  --reload-dir config \
  --reload-include ".env" \
  --reload-include ".env.local"

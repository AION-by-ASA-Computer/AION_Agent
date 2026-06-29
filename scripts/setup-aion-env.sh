#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE="$ROOT/scripts/setup_core.py"
AION=$'\033[1;31m'
RST=$'\033[0m'

print_banner() {
  echo ""
  echo -e "${AION}"
  cat <<'ART'
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
ART
  echo -e "${RST}"
  echo ""
}

if [[ ! -f "$CORE" ]]; then
  echo "Missing $CORE" >&2
  exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "Python not found. Please install Python 3." >&2
    exit 2
  fi
fi

dry_run=0
docker_mode=0
forwarded=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    --docker)  docker_mode=1 ;;  # short-hand: Docker preset (no venv, copies .env.example)
    *)         forwarded+=("$arg") ;;
  esac
done

if [[ "$docker_mode" -eq 1 ]]; then
  print_banner
  echo "[setup] Docker preset selected."
  if [[ -f "$ROOT/.env" && "$dry_run" -ne 1 ]]; then
    bak="$ROOT/.env.bak.$(date -u +%Y%m%d_%H%M%S)"
    cp "$ROOT/.env" "$bak"
    echo "[setup] Backup created: $bak"
  fi
  if [[ "$dry_run" -ne 1 ]]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo "[setup] Copied .env.example -> .env (edit DOMAIN, CADDY_* ports, AION_API_URL, secrets)"
  else
    echo "[dry-run] Would copy .env.example -> .env"
  fi
  echo ""
  echo "Next steps:"
  echo "  vim .env                                  # DOMAIN, CADDY_HTTP_PORT/CADDY_HTTPS_PORT (se 80/443 occupate), secrets"
  echo "  docker compose up -d --build              # full prod stack"
  echo "  docker compose -f docker-compose.dev.yml up   # dev essentials only"
  exit 0
fi

extra=()
if [[ "$dry_run" -ne 1 ]]; then
  extra+=(--prepare-runtime)
fi
if [[ "$dry_run" -eq 1 ]]; then
  forwarded+=(--dry-run)
fi

print_banner
# Nota: su bash 3.2 (macOS) con `set -u`, espandere un array vuoto come
# `"${arr[@]}"` solleva "unbound variable". Il pattern `${arr[@]+"${arr[@]}"}"`
# espande l'array solo se e' definito/non vuoto.
if [[ ${#extra[@]} -gt 0 ]]; then
  exec "$PYTHON_BIN" "$CORE" "${extra[@]}" ${forwarded[@]+"${forwarded[@]}"}
else
  exec "$PYTHON_BIN" "$CORE" ${forwarded[@]+"${forwarded[@]}"}
fi

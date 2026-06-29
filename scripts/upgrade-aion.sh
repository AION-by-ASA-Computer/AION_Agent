#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE="$ROOT/scripts/upgrade_core.py"

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
║                         ·  u p g r a d e   s c r i p t  ·                          ║
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
for arg in "$@"; do
  [[ "$arg" == "--dry-run" ]] && dry_run=1
  [[ "$arg" == "--docker" ]] && docker_mode=1
done

extra=()
# Skip venv prep in Docker mode (no local virtualenv needed)
if [[ "$dry_run" -ne 1 && "$docker_mode" -ne 1 ]]; then
  extra+=(--prepare-runtime)
fi

print_banner
if [[ "$docker_mode" -eq 1 ]]; then
  echo "[upgrade] Docker compose mode — will rebuild images + restart services."
fi
if [[ ${#extra[@]} -gt 0 ]]; then
  exec "$PYTHON_BIN" "$CORE" "${extra[@]}" "$@"
else
  exec "$PYTHON_BIN" "$CORE" "$@"
fi

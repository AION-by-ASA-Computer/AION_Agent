#!/usr/bin/env bash
# Install Podman rootless + configure AION session sandbox (container mode).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: python3 required" >&2
  exit 2
fi

exec "$PYTHON_BIN" "$ROOT/scripts/setup_podman_sandbox.py" "$@"

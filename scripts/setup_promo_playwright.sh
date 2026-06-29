#!/usr/bin/env bash
# Install Playwright + Chromium for promo_render MCP (NOT the session sandbox venv).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY=""
for CAND in \
  "${ROOT}/.venv/bin/python" \
  "${ROOT}/mcp_servers/promo_render/.venv/bin/python"; do
  if [[ -x "${CAND}" ]]; then
    PY="${CAND}"
    break
  fi
done
if [[ -z "${PY}" ]]; then
  PY="$(command -v python3)"
fi

# uv-managed venvs often have no ``pip`` module; use ``uv pip`` into .venv instead.
if command -v uv >/dev/null 2>&1 && [[ -x "${ROOT}/.venv/bin/python" ]]; then
  echo "Using uv pip -> ${ROOT}/.venv"
  (cd "${ROOT}" && uv pip install "playwright>=1.49.0")
  "${ROOT}/.venv/bin/python" -m playwright install chromium
elif "${PY}" -m pip --version >/dev/null 2>&1; then
  echo "Using Python: ${PY}"
  "${PY}" -m pip install -U "playwright>=1.49.0"
  "${PY}" -m playwright install chromium
else
  echo "ERROR: no pip (python -m pip) and uv not available — cannot install Playwright." >&2
  echo "  Install with: uv pip install playwright && .venv/bin/python -m playwright install chromium" >&2
  exit 1
fi

echo ""
echo "Verify from Graphic Designer chat:"
echo "  promo_check_environment  -> ok: true"
echo ""
echo "Python used: ${PY:-${ROOT}/.venv/bin/python}"

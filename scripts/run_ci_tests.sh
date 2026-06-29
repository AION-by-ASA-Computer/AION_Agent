#!/usr/bin/env bash
# Curated pytest modules for CI (no live LLM, no external services).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODULES=(
  src/test/test_api_endpoints.py
  src/test/test_session_env.py
  src/test/test_session_sandbox_escape.py
  src/test/test_mcp_catalog_install.py
  src/test/test_data_git_tracking.py
)

echo "==> CI pytest modules: ${#MODULES[@]}"
uv run python -m pytest "${MODULES[@]}" -v --tb=short "$@"

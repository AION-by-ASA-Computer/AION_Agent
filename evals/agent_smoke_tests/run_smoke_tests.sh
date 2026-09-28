#!/usr/bin/env bash
# Bash helper script to execute AION Agent Smoke Tests directly from CLI
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

PYTHON_BIN="python3"
if [ -f "${REPO_ROOT}/.venv/bin/python" ]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
elif [ -f "${REPO_ROOT}/.venv/Scripts/python.exe" ]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/Scripts/python.exe"
fi

"${PYTHON_BIN}" evals/agent_smoke_tests/test_runner.py "$@"

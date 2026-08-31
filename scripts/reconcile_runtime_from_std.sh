#!/usr/bin/env bash
# Allinea config/ runtime (profili, skill, native tool registry, MCP) a config_std/.
# Sicuro per Docker: ./config è bind-mountato; non tocca data/ né segreti .env.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON_BIN:-python3}"

echo "==> Reconcile profiles (force da config_std, ignora customizzazioni locali)"
"$PY" scripts/sync_config.py --profiles-only --force --reconcile-profiles-from-std

echo "==> Sync skills + registry nativo + resto config/"
"$PY" scripts/sync_config.py --force
"$PY" scripts/sync_config.py --skills-only --force

if [[ -f scripts/sync_proprietary_config.py ]]; then
  echo "==> Sync config_proprietary (skill report/docx, …)"
  "$PY" scripts/sync_proprietary_config.py --force
fi

echo "==> Sync MCP servers + merge registry"
"$PY" scripts/sync_mcp_servers.py --force
if [[ -f scripts/merge_mcp_registry_from_std.py ]]; then
  "$PY" scripts/merge_mcp_registry_from_std.py
fi

echo ""
echo "[ok] Runtime config allineato a config_std."
echo "     Riavvia il backend: docker compose restart backend  (o podman compose)"

#!/bin/sh
# Sync versioned templates (*_std) into writable runtime dirs before uvicorn.
# Controlled by AION_SYNC_ON_BOOT (default 1). Set to 0 to skip (debug only).
set -e

if [ "${AION_SYNC_ON_BOOT:-1}" = "1" ]; then
  echo "[aion-entrypoint] Syncing config_std -> config ..."
  python scripts/sync_config.py --force
  echo "[aion-entrypoint] Syncing mcp_servers_std -> mcp_servers ..."
  python scripts/sync_mcp_servers.py --force
  if [ -f scripts/merge_mcp_registry_from_std.py ]; then
    echo "[aion-entrypoint] Merging new MCP slugs from config_std -> config/mcp_registry.yaml ..."
    python scripts/merge_mcp_registry_from_std.py
  fi
  echo "[aion-entrypoint] Reconciling .env <-> data/runtime.env ..."
  python scripts/sync_runtime_env.py
  if [ -f scripts/seed_mcp_integration_configs.py ]; then
    echo "[aion-entrypoint] Syncing MCP connector integration catalog & registry ..."
    python scripts/seed_mcp_integration_configs.py
    python scripts/sync_mcp_integration_from_catalog.py
  fi
else
  echo "[aion-entrypoint] AION_SYNC_ON_BOOT=0 — skipping config/MCP sync"
fi

exec "$@"

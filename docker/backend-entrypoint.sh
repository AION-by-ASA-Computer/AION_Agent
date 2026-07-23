#!/bin/sh
# Sync versioned templates (*_std) into writable runtime dirs before uvicorn.
# Controlled by AION_SYNC_ON_BOOT (default 1). Set to 0 to skip (debug only).
set -e

if [ "${AION_SYNC_ON_BOOT:-1}" = "1" ]; then
  echo "[aion-entrypoint] Syncing config_std -> config ..."
  python scripts/sync_config.py --force
  echo "[aion-entrypoint] Syncing mcp_servers_std -> mcp_servers ..."
  python scripts/sync_mcp_servers.py --force
  echo "[aion-entrypoint] Reconciling .env <-> data/runtime.env ..."
  python scripts/sync_runtime_env.py
else
  echo "[aion-entrypoint] AION_SYNC_ON_BOOT=0 — skipping config/MCP sync"
fi

exec "$@"

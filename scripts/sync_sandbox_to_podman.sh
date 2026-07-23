#!/usr/bin/env bash
# Sync aion/sandbox:latest from Docker into Podman (backend uses Podman, not Docker, for sessions).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "Building sandbox image (Docker)..."
docker compose --profile sandbox-build build sandbox

echo "Importing into Podman..."
docker save aion/sandbox:latest | podman load
podman tag aion/sandbox:latest docker.io/aion/sandbox:latest 2>/dev/null || true

echo "Stopping running session sandbox containers (will respawn on next chat)..."
mapfile -t running < <(podman ps -q --filter label=aion.component=session_sandbox || true)
if ((${#running[@]})); then
  podman stop "${running[@]}"
fi

echo "Done. Images:"
docker images aion/sandbox --format 'docker  {{.ID}} {{.CreatedAt}}'
podman images aion/sandbox --format 'podman  {{.ID}} {{.CreatedAt}}' 2>/dev/null || true
podman images docker.io/aion/sandbox --format 'podman  {{.ID}} {{.CreatedAt}}' 2>/dev/null || true

echo "Restart backend if needed: docker compose up -d backend"

---
title: Podman sandbox deploy
sidebar_position: 4
description: Podman rootless setup for per-session sandbox containers in Docker Compose.
---

# Podman sandbox deployment

Production session isolation uses **Podman rootless** on the host. The backend container mounts the Podman socket and spawns `aion/sandbox` workers via `podman run -i`.

## Quick setup (recommended)

From the repo root on Linux:

```bash
./scripts/setup-podman-sandbox.sh
```

The script:

1. Installs Podman (apt/dnf/pacman) if missing
2. Enables `podman.socket` for the current user (rootless)
3. Removes/fixes a bogus socket **directory** if Docker Compose started before Podman
4. Creates `data/sessions/` on the host (bind-mount for sandbox)
5. Writes sandbox variables to `.env` (block `# --- Podman session sandbox ---`)
6. Builds `aion/sandbox:latest` with Docker and loads it into Podman
7. Optionally rebuilds the backend container

Flags: `--dry-run`, `--skip-install`, `--skip-build`, `-y` (non-interactive restart).

## Host setup (manual)

```bash
# Install Podman (Debian/Ubuntu example)
sudo apt-get install -y podman

# Enable rootless socket for deploy user
loginctl enable-linger $USER
systemctl --user enable --now podman.socket

# Verify
podman info
ls -l /run/user/$(id -u)/podman/podman.sock
```

Set in `.env` for Compose (or use `./scripts/setup-podman-sandbox.sh`):

```bash
AION_PODMAN_SOCKET_HOST=/run/user/1000/podman/podman.sock
AION_SANDBOX_BACKEND=container
AION_SANDBOX_HOST_DATA_DIR=/path/to/AION_Agent/data
AION_SANDBOX_HOST_UID=1000
AION_SANDBOX_HOST_GID=1000
AION_CONTAINER_RUNTIME=podman
AION_SANDBOX_CONTAINER_IMAGE=aion/sandbox:latest
AION_SANDBOX_FAIL_CLOSED=1
```

## Build sandbox image

```bash
docker compose --profile sandbox-build build sandbox
# Tag for Podman on host (if backend uses host socket)
podman tag aion/sandbox:latest localhost/aion/sandbox:latest
```

Or build directly with Podman:

```bash
podman build -f docker/Dockerfile.sandbox -t aion/sandbox:latest .
```

## Compose integration

`docker-compose.yml` mounts the Podman socket into the backend:

```yaml
volumes:
  - ${AION_PODMAN_SOCKET_HOST}:/run/podman/podman.sock
environment:
  AION_PODMAN_SOCKET: /run/podman/podman.sock
  CONTAINER_HOST: unix:///run/podman/podman.sock
```

The backend image includes the `podman` CLI client (no in-container daemon).

## SELinux (RHEL/Fedora)

Session bind mounts use the `:Z` suffix by default (`AION_SANDBOX_CONTAINER_SELINUX=1`). Disable only on hosts without SELinux:

```bash
AION_SANDBOX_CONTAINER_SELINUX=0
```

## Network egress

Default container network is `none`. When `AION_SANDBOX_ALLOW_PACKAGE_INSTALL=1` or npm install is enabled, containers use `slirp4netns` for outbound access (PyPI/npm). Restrict further with host firewall or set installs to `0` in production.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `container runtime unavailable` | Check socket mount path and `podman info` on host |
| Socket path is a **directory** | `docker compose stop backend && sudo rm -rf /run/user/$(id -u)/podman/podman.sock && systemctl --user start podman.socket` |
| Permission denied on volume | SELinux `:Z` or UID mapping; ensure session dir owned by host user |
| Permission denied `/opt/venv/bin/python` | Do not chmod session `.venv` symlinks; update to latest `container_runtime.py` and recreate backend |
| Orphan `aion-sandbox-*` containers | `podman ps -a --filter label=aion.component=session_sandbox`; stop manually |
| macOS dev | Use `AION_SANDBOX_BACKEND=subprocess` (no Podman socket) |

## Security notes

- Do **not** mount `/var/run/docker.sock` unless required; prefer Podman rootless
- Backend runs as root inside its container today; socket access is the main privilege boundary
- Future: dedicated orchestrator service so backend has no container socket

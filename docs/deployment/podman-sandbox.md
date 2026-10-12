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

Flags: `--dry-run`, `--skip-install`, `--skip-build`, `-y` (non-interactive restart),
`--image <ref>` (sandbox image written to `.env`; a registry-qualified ref such as
`ghcr.io/...:1.6.1` is pulled with `podman pull` instead of built with Docker),
`--compose-file <file>` (compose file used for build/restart, e.g. `docker-compose.ghcr.yml`).

### GHCR installer

`scripts/install.sh` downloads both setup scripts and runs them on Linux (step 4.5,
before the stack starts) with the versioned `ghcr.io/aion-by-asa-computer/aion-sandbox`
image and `docker-compose.ghcr.yml`. When launched via `sudo`, Podman rootless is
configured for `$SUDO_USER`; plain root is skipped. Use `--no-podman`
(or `AION_SKIP_PODMAN=1`) to keep the subprocess sandbox. A failed Podman setup is
non-fatal: the installer prints the command to retry.

`install.sh upgrade` keeps the sandbox in step with the backend on every hop: it runs
`podman pull ghcr.io/aion-by-asa-computer/aion-sandbox:<next>` as the rootless user
(`$SUDO_USER` under sudo) and rewrites `AION_SANDBOX_CONTAINER_IMAGE` in `.env`.
Custom images (e.g. `localhost/aion/sandbox:<branch>`) are left untouched; if the pull
fails the previous image is kept and a warning is printed.

`AION_SANDBOX_LIVE_SRC` defaults by image when unset: `0` for registry-qualified images
(`ghcr.io/...`), `1` for local ones (`aion/sandbox:latest`, `localhost/...`). `.env` files
from older installs therefore need no change.

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

### Testing an unreleased sandbox fix

With `AION_SANDBOX_LIVE_SRC=0` (GHCR installs) the sandbox runs the `src/` baked into the image, so a backend rebuild alone does not change sandbox behaviour. Build both from the branch:

```bash
cd ~/AION_Agent && git pull
podman build -f docker/Dockerfile.sandbox -t localhost/aion/sandbox:<branch> .
docker build -f docker/Dockerfile.backend -t aion/backend:<branch> .
# install dir .env (replace every occurrence):
sed -i 's|^AION_SANDBOX_CONTAINER_IMAGE=.*|AION_SANDBOX_CONTAINER_IMAGE=localhost/aion/sandbox:<branch>|' ~/aion-agent/.env
cd ~/aion-agent && docker compose -f docker-compose.ghcr.yml -f docker-compose.local.yml up -d --force-recreate backend
# check the fix is in the image:
podman run --rm --entrypoint grep localhost/aion/sandbox:<branch> -n "<marker>" /app/src/<file>.py
```

`docker-compose.local.yml` is a local override (not in the repo) that points the backend service at `image: aion/backend:<branch>`.
Re-running `setup-podman-sandbox.sh --image ghcr.io/...` rewrites the `.env` block back to the registry image.

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

Default container network is `none`. When `AION_SANDBOX_ALLOW_PACKAGE_INSTALL=1` or npm install is enabled, containers use `slirp4netns` for outbound access (PyPI/npm). slirp4netns does not expose host loopback services, but the LAN and internet are reachable. Restrict further with host firewall or set both installs to `0` in production (`--network=none`).

## Isolation model

In container mode the **container itself is the isolation boundary**. A session worker is started with:

```text
podman run --rm -i --init
  --cap-drop=ALL --security-opt no-new-privileges --read-only
  --tmpfs /tmp:rw,noexec,nosuid,size=256m
  -v <host>/data/sessions/<id>:/session:rw,Z
  --memory 512m --cpus 1.0 --pids-limit 256
  --network=none|slirp4netns
  --userns=keep-id --user <uid>:<gid>   # or --user 0:0 (AION_SANDBOX_CONTAINER_USERNS=root)
  <sandbox image>
```

What a script running in the sandbox can see:

| Resource | Access |
|----------|--------|
| `/session` (this session only) | read/write, owned by the host user |
| `/tmp` | tmpfs, `noexec`, discarded on exit |
| Rest of `/` | **image** filesystem (`/app`, `/opt/venv`, Debian base), read-only |
| Host filesystem, other sessions, `.env`, Podman socket | not mounted |
| Read-only extras | `config/fs_policy.yaml` when configured; host `src/` + `requirements-sandbox-skills.txt` only when `AION_SANDBOX_LIVE_SRC=1` |

:::note Listing `/` from a script is expected
`os.listdir("/")` inside the sandbox returns the container root (`app`, `opt`, `session`, `bin`, `etc`, …), which looks like a Linux host root but is the image filesystem. To verify, compare with:

```bash
podman run --rm --entrypoint ls <sandbox image> -la /   # same as the chat output
ls -la /                                                 # real host root
```

The host root shows e.g. `/home/<user>`, `/snap`, `/swap.img`; the container `/home` is empty and `/etc/hostname` is the container id. If host-only paths ever appear in sandbox output, treat it as a mount misconfiguration and inspect the `podman run` argv.
:::

Privileges: rootless Podman maps container uid 0 to the **host deploy user**, never to host root. With `AION_SANDBOX_CONTAINER_USERNS=root` the worker is uid 0 in the container but has no capabilities; with `keep-id` it runs as the host uid directly. In both cases a container escape lands on the unprivileged deploy user.

The second confinement layer (Landlock + Python `open`/`os`/`pathlib` guards from `sandbox_subprocess_entry`) is applied only with `AION_SANDBOX_BACKEND=subprocess`. In container mode user scripts are not additionally restricted to `/session` and can read the image filesystem; they cannot read anything from the host beyond the mounts above.

Production hardening checklist:

- `AION_SANDBOX_ALLOW_PACKAGE_INSTALL=0` and `AION_SANDBOX_ALLOW_NPM_INSTALL=0` → `--network=none`
- `AION_SANDBOX_LIVE_SRC=0` (default for registry images) → no host source mounted
- `AION_SANDBOX_FAIL_CLOSED=1` → no silent fallback to subprocess mode
- Keep the sandbox image free of secrets; it is fully readable by user code

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `container runtime unavailable` | Check socket mount path and `podman info` on host |
| Socket path is a **directory** | `docker compose stop backend && sudo rm -rf /run/user/$(id -u)/podman/podman.sock && systemctl --user start podman.socket` |
| Permission denied on volume | SELinux `:Z` or UID mapping; ensure session dir owned by host user |
| Permission denied `/opt/venv/bin/python` | Do not chmod session `.venv` symlinks; update to latest `container_runtime.py` and recreate backend |
| `crun: make .../merged private: Permission denied` (any `--userns=keep-id` run fails, also with runc) | `AION_SANDBOX_CONTAINER_USERNS=root`: sandbox runs as container root, which rootless Podman maps to the host user. The setup script probes this and sets it automatically |
| `path fuori dalla sessione` running any script (`sandbox_run_python_file`) | Bug in 1.6.1: the session `.venv/bin/python` symlink points outside the session and was rejected by the realpath confinement. Fixed in `session_venv_python`; with `AION_SANDBOX_LIVE_SRC=0` the **sandbox image** must contain the fix (see below) |
| `.env` change to `AION_SANDBOX_CONTAINER_IMAGE` ignored | Check for duplicate keys (`grep -n AION_SANDBOX_CONTAINER_IMAGE .env`, the last one wins: the setup script block may override yours) and recreate with `docker compose ... up -d --force-recreate backend`. Verify with `docker compose exec backend env \| grep SANDBOX_CONTAINER_IMAGE` |
| Old behaviour after switching image | Running session workers keep their image: `podman rm -f $(podman ps -aq --filter label=aion.component=session_sandbox)` and open a new chat |
| Orphan `aion-sandbox-*` containers | `podman ps -a --filter label=aion.component=session_sandbox`; stop manually |
| macOS dev | Use `AION_SANDBOX_BACKEND=subprocess` (no Podman socket) |

## Security notes

- Do **not** mount `/var/run/docker.sock` unless required; prefer Podman rootless
- Backend runs as root inside its container today; socket access is the main privilege boundary
- Future: dedicated orchestrator service so backend has no container socket

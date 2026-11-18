---
title: Releases and versioning
sidebar_position: 2
description: How AION versions are numbered, released and published as container images.
---

# Releases and versioning

This page explains how a new AION version is produced: how the version number is chosen, how releases are cut automatically from `main`, and where the ready-to-run container images are published. It also covers how an existing installation is upgraded. Read it if you contribute code, maintain the release pipeline, or operate an AION installation.

AION uses [Semantic Versioning](https://semver.org/) starting at **0.1.0** (pre-1.0: breaking changes are allowed).

| Artifact | Location |
|----------|----------|
| App version | `version.json` (bumped by release-please) |
| Python SDK | `sdk/python` (`aion-client`, same version) |
| Changelog | `CHANGELOG.md` (Keep a Changelog) |
| Git tag | `vX.Y.Z` on `main` |
| Container images | `ghcr.io/aion-by-asa-computer/aion-*` |

Sandbox images are **not** published to GHCR — build locally with `docker compose --profile sandbox-build build sandbox`.

## Automated releases (release-please)

On every push to `main`, [release-please](https://github.com/googleapis/release-please) opens or updates a **Release PR** when there are releasable commits.

**Commit messages** should follow [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Release bump |
|--------|----------------|
| `feat:` | Minor (0.1.0 → 0.2.0) |
| `fix:` | Patch (0.1.0 → 0.1.1) |
| `feat!:` or `BREAKING CHANGE:` | Major when on 1.x+ |
| `chore:`, `docs:` | Usually no release (or patch if configured) |

Workflow: [`.github/workflows/release-please.yml`](https://github.com/AION-by-ASA-Computer/AION_Agent/blob/main/.github/workflows/release-please.yml)

### GitHub token (`RELEASE_PLEASE_TOKEN`)

Release-please must use a **Personal Access Token** stored as the repository secret
`RELEASE_PLEASE_TOKEN`. The default `GITHUB_TOKEN` creates releases that **do not**
trigger [`.github/workflows/release-images.yml`](https://github.com/AION-by-ASA-Computer/AION_Agent/blob/main/.github/workflows/release-images.yml)
(GitHub loop-prevention).

**Fine-grained PAT** (recommended) on the org account:

| Setting | Value |
|---------|--------|
| Repository access | `AION_Agent` only |
| Contents | Read and write |
| Pull requests | Read and write |
| Metadata | Read |

**Classic PAT** alternative: scope `repo` (full).

Store the secret:

```bash
gh secret set RELEASE_PLEASE_TOKEN --repo AION-by-ASA-Computer/AION_Agent
# paste the PAT when prompted
```

### First release (0.1.0)

1. Merge pending work to `main` (including this release setup).
2. Wait for the **Release PR** (`chore: release 0.1.0`) from release-please.
3. Review changelog + version bumps in the PR (`version.json`, `sdk/python/pyproject.toml`).
4. Merge the Release PR → GitHub creates tag **`v0.1.0`** and a GitHub Release.

### Subsequent releases

1. Land changes on `main` with conventional commits.
2. Release-please updates the Release PR.
3. Merge when ready → new tag + GitHub Release.

## Container images (GHCR)

When a GitHub Release is **published**, [`.github/workflows/release-images.yml`](https://github.com/AION-by-ASA-Computer/AION_Agent/blob/main/.github/workflows/release-images.yml) builds and pushes:

| Image | Dockerfile |
|-------|------------|
| `ghcr.io/aion-by-asa-computer/aion-backend` | `docker/Dockerfile.backend` |
| `ghcr.io/aion-by-asa-computer/aion-chat-ui` | `docker/Dockerfile.chat-ui` |
| `ghcr.io/aion-by-asa-computer/aion-admin-ui` | `docker/Dockerfile.admin-ui` |
| `ghcr.io/aion-by-asa-computer/aion-website` | `docker/Dockerfile.website` |

Each image is tagged with **`X.Y.Z`** (from the release tag) and **`latest`**.

Published platforms: **`linux/amd64`** and **`linux/arm64`** (Apple Silicon, ARM servers).

**Production:** pin an explicit version, e.g. `AION_VERSION=1.0.0`. Do not rely on `latest` in production.

### Deploy from GHCR

The recommended way to deploy pre-built images is using the standalone installer:

```bash
# Latest release (dev/staging):
curl -fsSL https://raw.githubusercontent.com/AION-by-ASA-Computer/AION_Agent/main/scripts/install.sh | bash

# Pinned version (production):
curl -fsSL https://raw.githubusercontent.com/AION-by-ASA-Computer/AION_Agent/main/scripts/install.sh | bash -s -- --version 1.0.0
```

### Upgrading an existing GHCR installation {#upgrade-di-uninstallazione-ghcr-esistente}

To update an existing installation **without reinstalling**, run the
command from the installation directory (where `.env` and
`docker-compose.ghcr.yml` live):

```bash
# Upgrade to the latest stable version:
curl -fsSL https://raw.githubusercontent.com/AION-by-ASA-Computer/AION_Agent/main/scripts/install.sh | bash -s -- upgrade

# Upgrade to a specific version (intermediate versions are traversed automatically as hops):
curl -fsSL https://raw.githubusercontent.com/AION-by-ASA-Computer/AION_Agent/main/scripts/install.sh | bash -s -- upgrade --version 1.6.0

# Non-interactive mode (CI / automation):
curl -fsSL https://raw.githubusercontent.com/AION-by-ASA-Computer/AION_Agent/main/scripts/install.sh | bash -s -- upgrade --yes
```

The command automatically performs:

- **Backup** — creates an archive `data/_backups/aion_backup_<ts>.tar.gz` before touching any file.
- **Sequential hops** — walks through every intermediate version in order (never a direct jump). Going from `1.4.0` to `1.6.0`, the path is `1.4.0 → 1.5.0 → 1.6.0`.
- **Lock** — prevents concurrent runs (`data/.upgrade.lock`).
- **Selective `.env` update** — only changes `AION_VERSION`; all customizations stay intact.
- **`docker pull + up -d`** — updates the images and restarts the containers.
- **Health check** — verifies that the backend answers on `/api/health` after every hop.
- **Idempotency** — if a hop fails, the script stops. A new `upgrade` resumes exactly from the hop after the last one applied.

Local `config/` and `mcp_servers/` are never overwritten.

**From the admin-ui**: with the `aion-updater` sidecar running (the default since
`install.sh` configures it), the same flow starts from the **Update now** button
of the version banner, with real-time progress. See
[Updating from the admin-ui](../deployment/self-update.md).

#### Note for contributors (per-version upgrade files)

When a release introduces new, renamed or removed `.env` keys, add
`scripts/upgrades/<new_version>.py` in the same PR:

```python
# scripts/upgrades/1.6.0.py
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from upgrade_lib import UpgradeContext

def upgrade(ctx: UpgradeContext) -> None:
    ctx.ensure_env_key("AION_NEW_FEATURE_FLAG", "0")
    ctx.rename_env_key("AION_OLD_NAME", "AION_NEW_NAME")
```

See `scripts/upgrades/README.md` for the full documentation of the contract.

### Build locally (default)

```bash
docker compose up -d --build
```

See also [Docker deployment](../deployment/docker.md).

## GitHub Packages visibility

After the first image push, set package visibility to **public** under the org’s GitHub Packages settings so pull works without authentication.

## Backfill / manual image publish

If a release was published before `RELEASE_PLEASE_TOKEN` was configured, run the workflow manually:

```bash
gh workflow run "Publish container images" \
  --repo AION-by-ASA-Computer/AION_Agent \
  -f tag_name=v1.0.0
```

Or use **Actions → Publish container images → Run workflow** in the GitHub UI.

## Manual release (fallback)

```bash
# Only if automation is unavailable — prefer the Release PR flow.
gh release create v0.1.0 --title "v0.1.0" --notes-file CHANGELOG-excerpt.md
```

Pushing the tag or publishing the release triggers the image workflow.

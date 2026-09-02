---
title: Releases and versioning
sidebar_position: 2
description: SemVer, release-please, GitHub Releases, and GHCR container images.
---

# Releases and versioning

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

Workflow: [`.github/workflows/release-please.yml`](../../.github/workflows/release-please.yml)

### GitHub token (`RELEASE_PLEASE_TOKEN`)

Release-please must use a **Personal Access Token** stored as the repository secret
`RELEASE_PLEASE_TOKEN`. The default `GITHUB_TOKEN` creates releases that **do not**
trigger [`.github/workflows/release-images.yml`](../../.github/workflows/release-images.yml)
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

When a GitHub Release is **published**, [`.github/workflows/release-images.yml`](../../.github/workflows/release-images.yml) builds and pushes:

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

```bash
cp .env.example .env
./scripts/setup-aion-env.sh --docker

# Latest release (dev/staging):
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d --no-build

# Pinned version (production):
export AION_VERSION=1.0.0
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d --no-build
```

`--no-build` is **required**: the `build:` section in `docker-compose.yml` cannot be
removed by an override, so without the flag Compose rebuilds the image from the local
source whenever it is not already in cache.

### What the GHCR overlay changes

`docker-compose.ghcr.yml` does two things, not one:

1. replaces `image:` with the GHCR reference for the four app services;
2. rewrites the backend `volumes` list with the YAML tag `!override`, dropping the
   `./src`, `./config_std`, `./mcp_servers_std` and `requirements-sandbox-skills.txt`
   bind-mounts.

Step 2 is what makes the pulled image actually run. A bind-mount always shadows the
image content at that path, so leaving `./src:/app/src` in place would keep executing
the code of the local git clone regardless of which image was pulled. Only the
**state** mounts survive: `aion_data`, `.env`, `data/sessions`, `data/db_test`, the
Podman socket, and the writable `config/` + `mcp_servers/` overlays holding customer
customizations.

Consequence: in GHCR mode the code comes from the image, so `git pull` is no longer
part of the upgrade — pulling a new image tag is.

**Requires Docker Compose >= 2.24** for the `!override` tag.

### Build locally (default)

```bash
docker compose up -d --build
```

In this mode the bind-mounts of the base file stay active, so `src/` and the `*_std/`
template dirs are served from the git clone: `git pull && docker compose restart backend`
propagates code changes without an image rebuild.

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

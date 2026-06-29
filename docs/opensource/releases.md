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

**Production:** pin an explicit version, e.g. `AION_VERSION=0.1.0`. Do not rely on `latest` in production.

### Deploy from GHCR

```bash
cp .env.example .env
./scripts/setup-aion-env.sh --docker

export AION_VERSION=0.1.0
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d --no-build
```

### Build locally (default)

```bash
docker compose up -d --build
```

See also [Docker deployment](../deployment/docker.md).

## GitHub Packages visibility

After the first image push, set package visibility to **public** under the org’s GitHub Packages settings so pull works without authentication.

## Manual release (fallback)

```bash
# Only if automation is unavailable — prefer the Release PR flow.
gh release create v0.1.0 --title "v0.1.0" --notes-file CHANGELOG-excerpt.md
```

Pushing the tag or publishing the release triggers the image workflow.

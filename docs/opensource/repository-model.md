---
title: Repository model
sidebar_position: 1
description: Public repository is the single source of truth. AION_Agent_V1 is a read-only private archive.
---

# Repository model

## Active repository (everyone works here)

**[github.com/AION-by-ASA-Computer/AION_Agent](https://github.com/AION-by-ASA-Computer/AION_Agent)** — public, single source of truth.

- All development, PRs, issues, and releases
- `git clone` / `git push` target for contributors
- CI runs on GitHub Actions (`ubuntu-latest`)

## Archive (do not push here)

**[github.com/AION-by-ASA-Computer/AION_Agent_V1](https://github.com/AION-by-ASA-Computer/AION_Agent_V1)** — private, frozen history from before the open-source cutover.

- Kept for internal audit and old PR/issue references
- **No new commits** — do not open PRs or push branches
- Not synced with the public repo

## Local clone setup

After the cutover, point `origin` at the **public** repo:

```bash
git remote rename origin archive    # only if origin still points at AION_Agent_V1
git remote add origin https://github.com/AION-by-ASA-Computer/AION_Agent.git
# or: git remote set-url origin https://github.com/AION-by-ASA-Computer/AION_Agent.git

git fetch origin
git checkout main
git branch -u origin/main
```

Optional: keep the archive as a read-only remote:

```bash
git remote add archive https://github.com/AION-by-ASA-Computer/AION_Agent_V1.git
```

## Workflow

1. Branch from `main` on **AION_Agent**
2. Open PR → review → merge to `main`
3. Tag releases on `main` when ready

No export step, no dual push, no `public-release` orphan branches in day-to-day work.

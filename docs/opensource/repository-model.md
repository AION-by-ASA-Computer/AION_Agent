---
title: Repository model
sidebar_position: 1
description: Single public repository for development, releases, and contributions.
---

# Repository model

## Active repository

**[github.com/AION-by-ASA-Computer/AION_Agent](https://github.com/AION-by-ASA-Computer/AION_Agent)** — public, single source of truth.

- All development, PRs, issues, and releases
- `git clone` / `git push` target for contributors
- CI on GitHub Actions (`ubuntu-latest`, hosted runners)

## Clone and work

```bash
git clone https://github.com/AION-by-ASA-Computer/AION_Agent.git
cd AION_Agent
git checkout main
```

## Workflow

1. Branch from `main`
2. Open PR → review → merge to `main`
3. Tag releases on `main` when ready (automated via [release-please](https://github.com/googleapis/release-please); see [releases.md](releases.md))

Branch ruleset on `main`: [`.github/BRANCH_PROTECTION.md`](../../.github/BRANCH_PROTECTION.md).

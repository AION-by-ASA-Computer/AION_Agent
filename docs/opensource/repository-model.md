---
title: Repository model
sidebar_position: 1
description: Where AION's code lives and how contributions flow into it.
---

# Repository model

AION is developed in a single public GitHub repository, which is the one place for code, issues, pull requests and releases. This page tells contributors where to clone from and how a change goes from a branch to a release.

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

Branch ruleset on `main`: [`.github/BRANCH_PROTECTION.md`](https://github.com/AION-by-ASA-Computer/AION_Agent/blob/main/.github/BRANCH_PROTECTION.md).

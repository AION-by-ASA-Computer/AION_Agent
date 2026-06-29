# Branch protection policy

Target: **`main`** on [AION-by-ASA-Computer/AION_Agent](https://github.com/AION-by-ASA-Computer/AION_Agent).

CI runs on **GitHub-hosted runners** (`ubuntu-latest`) — no self-hosted runner required.

## Prerequisites

1. At least one **green CI run** on `main` (so job names exist for required checks).
2. Repository secret **`GITLEAKS_LICENSE`** — same as the previous setup; required by `gitleaks/gitleaks-action@v2`.
   - **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `GITLEAKS_LICENSE`
   - Value: license from [gitleaks.io](https://gitleaks.io)

## Required settings (GitHub UI)

**Settings → Branches → Branch protection rules → Add rule → Branch name pattern: `main`**

| Setting | Value |
|---------|-------|
| Require a pull request before merging | On |
| Required approvals | 1 |
| Dismiss stale approvals | On |
| Require status checks to pass | On |
| Require branches to be up to date before merging | On |
| Required checks | See below |
| Require conversation resolution before merging | On |
| Do not allow bypassing the above settings | On (recommended) |
| Restrict force pushes | On |
| Allow force pushes | Off |
| Allow deletions | Off |

### Required status checks

Add these **job names** exactly as shown in the Actions tab (after a green run):

- `Backend Linting and Testing`
- `Frontend Packages Build`
- `Security Vulnerability Scanning`
- `Test Docker Builds`

## CLI setup (maintainers with admin access)

Run once after CI has passed at least once on `main`:

```bash
gh api \
  --method PUT \
  repos/AION-by-ASA-Computer/AION_Agent/branches/main/protection \
  -f required_status_checks[strict]=true \
  -f required_status_checks[contexts][]='Backend Linting and Testing' \
  -f required_status_checks[contexts][]='Frontend Packages Build' \
  -f required_status_checks[contexts][]='Security Vulnerability Scanning' \
  -f required_status_checks[contexts][]='Test Docker Builds' \
  -f enforce_admins=true \
  -f required_pull_request_reviews[required_approving_review_count]=1 \
  -f required_pull_request_reviews[dismiss_stale_reviews]=true \
  -f restrictions=null
```

If the API returns `404`, enable branch protection via the UI first, or confirm you have admin rights on the repository.

## Workflow after protection is enabled

1. Branch from `main`: `git checkout -b feature/my-change`
2. Push and open a PR to `main`
3. Wait for all four CI jobs to pass
4. Get one approval, merge via squash or merge commit

Direct pushes to `main` are blocked once protection is active.

# Branch protection policy

Target: **`main`** on [AION-by-ASA-Computer/AION_Agent](https://github.com/AION-by-ASA-Computer/AION_Agent).

## Required settings (GitHub UI)

**Settings → Branches → Branch protection rules → `main`**

| Setting | Value |
|---------|-------|
| Require a pull request before merging | On |
| Required approvals | 1 |
| Dismiss stale approvals | On |
| Require status checks | On |
| Require branch up to date | On |
| Required checks | See below |
| Require conversation resolution | On |
| Restrict force pushes | On |
| Include administrators | Off (recommended) |

### Required status checks

Enable after the first green CI run on `main`:

- `Backend Linting and Testing`
- `Frontend Packages Build`
- `Security Vulnerability Scanning`
- `Test Docker Builds`

## CLI setup (maintainers)

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

## Archive repo (AION_Agent_V1)

No branch protection changes needed — repository is read-only archive. Do not push new work there.

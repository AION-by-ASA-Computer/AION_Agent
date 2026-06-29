# Branch ruleset policy (`main`)

Target repository: **[AION-by-ASA-Computer/AION_Agent](https://github.com/AION-by-ASA-Computer/AION_Agent)**

This guide uses GitHub **repository rulesets** (Settings → **Rules** → **Rulesets**), not the legacy **Branch protection rules** page (Settings → Branches). Rulesets are the current model; they can coexist with old rules, but we recommend **only** the ruleset below to avoid duplicate or conflicting checks.

Official docs: [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets) · [Creating rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository) · [Available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)

CI runs on **GitHub-hosted runners** (`ubuntu-latest` in [`.github/workflows/ci.yml`](workflows/ci.yml)).

---

## Prerequisites

Complete these **before** creating the ruleset:

1. **One green CI run on `main`** — required status checks only appear in the UI after GitHub has seen those job names at least once.
2. **Repository secret `GITLEAKS_LICENSE`** (for `gitleaks/gitleaks-action@v2`):
   - **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `GITLEAKS_LICENSE`
   - Value: license from [gitleaks.io](https://gitleaks.io)
3. **Admin access** on the repository (to create rulesets).

### Remove legacy branch protection (if present)

If an old rule exists under **Settings → Branches → Branch protection rules** for `main`, delete it after the ruleset is active. Keeping both can stack rules and make troubleshooting harder.

---

## Step-by-step: create the ruleset (UI)

### 1. Open rulesets

1. Open `https://github.com/AION-by-ASA-Computer/AION_Agent`
2. **Settings** (repository admin only)
3. Left sidebar: **Rules** → **Rulesets**
4. **New ruleset** → **New branch ruleset**

### 2. Name and enforcement

| Field | Value |
|-------|-------|
| **Ruleset name** | `Protect main` (or any clear name) |
| **Enforcement status** | **Active** |

> On GitHub Enterprise you can use **Evaluate** first to test without blocking merges. On GitHub Free/Team, use **Active** once CI is green.

### 3. Bypass list

Leave **empty** for maximum strictness (no one bypasses the ruleset).

Optional (break-glass only): **Add bypass** → **Repository admin** → mode **For pull requests only** so admins still open PRs but cannot push directly to `main`.

Do **not** add broad bypass for all writers unless you intend to allow direct pushes.

### 4. Target branches

Under **Target branches** → **Add target**:

| Target type | Value |
|-------------|-------|
| **Include by pattern** | `main` |

Alternatively: **Include default branch** if `main` is the default branch.

Do not add broad patterns like `*` unless you intend to protect every branch.

### 5. Branch protections (rules)

Enable the following rules in **Branch protections**:

#### Restrict deletions

- **On** (default) — only bypass actors can delete `main`.

#### Restrict updates

- **On** — only bypass actors can push commits directly to `main`. Everyone else merges via pull request.

#### Block force pushes

- **On** (maps to rule **Block force pushes** / `non_fast_forward`) — prevents rewriting `main` history.

#### Require a pull request before merging

- **On**, then under **Additional settings**:

| Setting | Value |
|---------|-------|
| Required approvals | **1** |
| Dismiss stale pull request approvals when new commits are pushed | **On** |
| Require approval of the most recent reviewable push | Off (optional; enable for stricter review) |
| Require conversation resolution before merging | **On** |
| Allowed merge methods | At least one of **Squash**, **Merge**, **Rebase** (match repo preferences) |

#### Require status checks to pass before merging

- **On**, then:

| Setting | Value |
|---------|-------|
| **Require branches to be up to date before merging** | **On** (strict — branch must be rebased/updated before merge) |

Add each required check by name (must match the **job name** in Actions, not the workflow file name):

| Required status check |
|-----------------------|
| `Backend Linting and Testing` |
| `Frontend Packages Build` |
| `Security Vulnerability Scanning` |
| `Test Docker Builds` |

For each name: type it in the search box → select the suggestion → confirm with **+**.

If a check does not appear, trigger a successful workflow run on `main` first, then refresh this page.

**Source:** leave **Any source** unless you later pin checks to a specific GitHub App integration.

### 6. Create

Click **Create**. With enforcement **Active**, the ruleset applies immediately.

### 7. Verify

1. Open **Rules** → **Rulesets** — ruleset shows **Active** and targets `main`.
2. Try a direct push to `main` (should be rejected).
3. Open a test PR — merge should be blocked until CI is green and one approval is given.

---

## Required CI jobs (reference)

Defined in [`.github/workflows/ci.yml`](workflows/ci.yml):

```yaml
jobs:
  backend-checks:
    name: Backend Linting and Testing
  frontend-checks:
    name: Frontend Packages Build
  security-scan:
    name: Security Vulnerability Scanning
  docker-build-checks:
    name: Test Docker Builds
```

The ruleset must use these **`name:`** values, not the job IDs (`backend-checks`, etc.).

---

## Optional: create via REST API

For admins who prefer automation (after at least one green CI run on `main`):

```bash
gh api \
  --method POST \
  repos/AION-by-ASA-Computer/AION_Agent/rulesets \
  -f name='Protect main' \
  -f target=branch \
  -f enforcement=active \
  -f 'conditions[ref_name][include][]=refs/heads/main' \
  -f 'rules[][type]=deletion' \
  -f 'rules[][type]=update' \
  -f 'rules[][type]=non_fast_forward' \
  -f 'rules[][type]=pull_request' \
  -f 'rules[][parameters][required_approving_review_count]=1' \
  -f 'rules[][parameters][dismiss_stale_reviews_on_push]=true' \
  -f 'rules[][parameters][require_code_owner_review]=false' \
  -f 'rules[][parameters][require_last_push_approval]=false' \
  -f 'rules[][parameters][required_review_thread_resolution]=true' \
  -f 'rules[][type]=required_status_checks' \
  -f 'rules[][parameters][strict_required_status_checks_policy]=true' \
  -f 'rules[][parameters][required_status_checks][][context]=Backend Linting and Testing' \
  -f 'rules[][parameters][required_status_checks][][context]=Frontend Packages Build' \
  -f 'rules[][parameters][required_status_checks][][context]=Security Vulnerability Scanning' \
  -f 'rules[][parameters][required_status_checks][][context]=Test Docker Builds'
```

If `gh api` returns `422`, use the UI once to confirm check names, or send a JSON body per [REST: Create a repository ruleset](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset).

List existing rulesets:

```bash
gh api repos/AION-by-ASA-Computer/AION_Agent/rulesets
```

---

## Contributor workflow (after ruleset is active)

1. `git checkout main && git pull`
2. `git checkout -b feature/my-change`
3. Push and open a PR to `main`
4. Wait for all four CI jobs to pass
5. Obtain **one approving review**
6. Resolve all review conversations
7. Merge (squash, merge, or rebase — per allowed methods in the ruleset)

Direct pushes and force pushes to `main` are blocked.

---

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| Status check missing in ruleset UI | Run CI successfully on `main` first; use exact job `name` from workflow |
| Security job fails immediately | Add `GITLEAKS_LICENSE` repository secret |
| Merge blocked despite green CI | Branch out of date — click **Update branch** on the PR |
| Rules seem duplicated | Remove legacy rule under **Settings → Branches** |
| Admin can still push | Admin may be on bypass list — remove bypass or use **For pull requests only** |

More: [Troubleshooting rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/troubleshooting-rules).

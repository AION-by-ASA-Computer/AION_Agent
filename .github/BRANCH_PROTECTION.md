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

**Required when Restrict updates is enabled** (see below): add **Repository admin** → mode **For pull requests only**.

With **Restrict updates** on and an **empty** bypass list, approved PRs with green CI still fail to merge with *Cannot update this protected ref* — GitHub treats the merge as a ref update that only bypass actors may perform. **For pull requests only** lets admins merge via the PR UI after requirements pass; it does **not** allow direct pushes to `main`.

Do **not** use **Always allow** for broad roles unless you intend break-glass direct pushes. Do **not** add all writers to bypass.

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

- **On** — blocks direct pushes to `main` (only bypass actors can push). Merges also require a bypass actor with **For pull requests only** (or **Always allow**); pair with **Require a pull request before merging** below.
- **Off** — if you prefer fewer moving parts: **Require a pull request before merging** alone already blocks direct pushes for non-bypass users.

#### Block force pushes

- **On** (maps to rule **Block force pushes** / `non_fast_forward`) — prevents rewriting `main` history.

#### Require a pull request before merging

- **On**, then under **Additional settings**:

| Setting | Value |
|---------|-------|
| Required approvals | **2** (OpenSSF Scorecard tier 4) |
| Require review from Code Owners | **On** (requires [`.github/CODEOWNERS`](CODEOWNERS)) |
| Dismiss stale pull request approvals when new commits are pushed | **On** |
| Require approval of the most recent reviewable push | **On** (OpenSSF Scorecard tier 2 for administrators) |
| Require conversation resolution before merging | **On** |
| Allowed merge methods | At least one of **Squash**, **Merge**, **Rebase** (match repo preferences) |

> **OpenSSF Branch-Protection:** score **9** needs two approving reviews plus CODEOWNERS; score **10** also needs stale-review dismissal and rules that apply to administrators (empty bypass list, no **Always allow** for admins). See [Scorecard checks](https://github.com/ossf/scorecard/blob/main/docs/checks.md#branch-protection).

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
| `CodeQL Analysis (python)` |
| `CodeQL Analysis (javascript-typescript)` |

For each name: type it in the search box → select the suggestion → confirm with **+**.

If a check does not appear, trigger a successful workflow run on `main` first, then refresh this page.

> **CodeQL** runs from [`.github/workflows/codeql.yml`](workflows/codeql.yml). Matrix jobs appear as `CodeQL Analysis (python)` and `CodeQL Analysis (javascript-typescript)`. Add both after the first green CodeQL run, or require only one language while onboarding.

> **Dependabot** ([`.github/dependabot.yml`](dependabot.yml)) does not add merge-blocking checks. In **Settings → Security → Advanced Security**, enable **Dependabot alerts** if shown. **Dependabot security updates** on public repositories are often **always enabled** (no toggle, or button greyed out).
>
> Dependabot workflows **cannot read repository secrets** (including `GITLEAKS_LICENSE`). The gitleaks step in [ci.yml](workflows/ci.yml) is skipped for `dependabot[bot]`; Trivy still runs so **Security Vulnerability Scanning** can pass on dependency PRs.

Optional governance checks (add after first green run; not required for day-one merges):

| Check | Workflow |
|-------|----------|
| `Workflow Lint` | [governance.yml](workflows/governance.yml) |
| `Typos Check` | [governance.yml](workflows/governance.yml) |
| `Semantic PR Title` | [pull-request.yml](workflows/pull-request.yml) |
| `OSV-Scanner PR` | [osv-scanner.yml](workflows/osv-scanner.yml) (job `osv-scan`) |

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

CodeQL (optional fifth/sixth required checks) — [`.github/workflows/codeql.yml`](workflows/codeql.yml):

```yaml
jobs:
  analyze:
    name: CodeQL Analysis   # matrix: (python), (javascript-typescript)
```

The ruleset must use these **`name:`** values (plus matrix suffixes for CodeQL), not the job IDs (`backend-checks`, etc.).

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
  -f 'rules[][parameters][required_approving_review_count]=2' \
  -f 'rules[][parameters][dismiss_stale_reviews_on_push]=true' \
  -f 'rules[][parameters][require_code_owner_review]=true' \
  -f 'rules[][parameters][require_last_push_approval]=true' \
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
4. Wait for all CI jobs to pass (four core jobs; plus CodeQL if required in the ruleset)
5. Obtain **two approving reviews** (including **@AION-by-ASA-Computer/asa-core** when CODEOWNERS applies)
6. Resolve all review conversations
7. Merge (squash, merge, or rebase — per allowed methods in the ruleset)

Direct pushes and force pushes to `main` are blocked.

---

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| Status check missing in ruleset UI | Run CI successfully on `main` first; use exact job `name` from workflow |
| Security job fails immediately | Add `GITLEAKS_LICENSE` repository secret (not available to Dependabot — gitleaks is skipped for `dependabot[bot]`) |
| Merge blocked despite green CI | Branch out of date — click **Update branch**; missing **Approve** (comment ≠ approval); or **Restrict updates** with empty bypass — add **Repository admin** → **For pull requests only** |
| `Cannot update this protected ref` (API/UI) | **Restrict updates** is on and bypass list is empty (or merger lacks bypass). Add admin bypass **For pull requests only**, or disable **Restrict updates** and rely on **Require a pull request** |
| OSV Code Scanning: `configuration not found` on PRs | Legacy `osv-scanner-scheduled.yml` SARIF on `main` — use unified [osv-scanner.yml](workflows/osv-scanner.yml); after merge, re-run **OSV-Scanner** on `main` |
| Rules seem duplicated | Remove legacy rule under **Settings → Branches** |
| Admin can still push | Admin may be on bypass list — remove bypass or use **For pull requests only** |

More: [Troubleshooting rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/troubleshooting-rules).

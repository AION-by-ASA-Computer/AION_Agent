#!/usr/bin/env bash
# Legacy helper: create a one-commit snapshot (used only for the initial public cutover).
# Day-to-day development uses normal git flow on origin/main — see docs/opensource/repository-model.md
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Checking data/ is not tracked (except whitelist)..."
python3 scripts/check_data_git_tracking.py

echo "==> Creating orphan branch public-release..."
if git show-ref --verify --quiet refs/heads/public-release; then
  echo "Branch public-release already exists. Delete it first: git branch -D public-release"
  exit 1
fi

git checkout --orphan public-release
git add -A

echo "==> Staged files: $(git diff --cached --name-only | wc -l | tr -d ' ')"

if [[ "${1:-}" == "--commit" ]]; then
  git commit -m "$(cat <<'EOF'
Initial open-source release of AION Agent.

Apache-2.0 licensed agent platform with FastAPI backend, chat-ui, admin-ui,
and MCP tool integration.
EOF
)"
  echo "==> Commit created on public-release."
  echo "Push to public main: git push origin public-release:main"
else
  echo "Dry run: review with 'git status' and 'git diff --cached --stat'"
  echo "Then: ./scripts/prepare-oss-release.sh --commit"
fi

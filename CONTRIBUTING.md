# Contributing to AION Agent

Thank you for contributing. This is the active repository:

`https://github.com/AION-by-ASA-Computer/AION_Agent`

## Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) (recommended)
- [pnpm](https://pnpm.io/) 9+
- An OpenAI-compatible LLM endpoint (`AION_API_URL`)

## Fork and clone

```bash
git clone https://github.com/AION-by-ASA-Computer/AION_Agent.git
cd AION_Agent
# If you forked:
git remote add upstream https://github.com/AION-by-ASA-Computer/AION_Agent.git
```

## Local setup

```bash
cp .env.example .env
# Edit AION_API_URL, AION_MODEL, secrets

uv venv && uv pip install -r requirements.txt
uv pip install pytest pytest-asyncio ruff

./scripts/setup-aion-env.sh
```

Run the backend (single worker):

```bash
uvicorn src.api.main:app --reload --reload-exclude data/sessions
```

Run the chat UI:

```bash
cd chat-ui && pnpm install && pnpm dev
```

Import `src.aion_env` before any module that reads `os.environ` in scripts or tests.

## Branching and pull requests

1. **Branch from `main`** — use a descriptive name: `feat/plan-dock-shortcuts`, `fix/mcp-pool-leak`.
2. **Keep PRs focused** — one logical change per PR when possible.
3. **Run checks locally** before pushing (see below).
4. **Fill in the PR template** — summary, test plan, breaking changes.
5. **Target `main`** on `AION-by-ASA-Computer/AION_Agent`.

Maintainers review for correctness, security, and scope. At least **one approval** is required before merge (see [.github/BRANCH_PROTECTION.md](.github/BRANCH_PROTECTION.md)).

### What we do not merge

- Committed secrets, API keys, or `.env` files
- Runtime data under `data/` (except whitelisted `data/eval_datasets/`, `data/plugins/`)
- Internal hostnames, customer data, or personal paths in examples
- Unrelated drive-by refactors

## Code conventions

| Area | Rule |
|------|------|
| Python | Backend in `src/`; tests in `src/test/`; kebab-case doc filenames |
| Frontends | Next.js 16 + React 19; **pnpm only** |
| Config | Templates in `config_std/`; local `config/` is gitignored |
| Env vars | Prefix `AION_`; document new vars in `.env.example` |
| API | Paths use `/v1/` prefix |

See [AGENTS.md](AGENTS.md) for MCP serialization, session constraints, and monorepo layout.

## Tests and CI

CI runs on **GitHub-hosted** `ubuntu-latest` (see [.github/workflows/ci.yml](.github/workflows/ci.yml)).

### Run the same checks locally

```bash
# Sync config (CI step)
uv run python scripts/setup_core.py --non-interactive --skip-promo-playwright

# Lint
uv run ruff check --config ruff.toml src/
uv run ruff format --check --config ruff.toml src/

# Data tracking guard
python scripts/check_data_git_tracking.py

# Curated pytest (no live LLM)
AION_CHAT_PASSWORD_AUTH=0 AION_ADMIN_PASSWORD_AUTH=0 AION_REDIS_FALLBACK_LOCAL=1 \
  ./scripts/run_ci_tests.sh
```

### Frontend (when UI changes)

```bash
cd chat-ui && pnpm install && pnpm build
cd admin-ui && pnpm install && pnpm build
```

Add or update tests when you change behavior. Prefer extending `scripts/run_ci_tests.sh` for stable unit coverage.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) — release-please uses them to bump versions and update `CHANGELOG.md`:

| Prefix | Typical bump |
|--------|----------------|
| `feat:` | Minor |
| `fix:` | Patch |
| `docs:`, `chore:`, `ci:` | Usually no release unless user-facing |

Examples:

- `fix: reject sandbox paths outside session workspace`
- `feat: expose reasoning effort in chat settings API`
- `docs: update Docker quick start in README`

Releases and GHCR images: [docs/opensource/releases.md](docs/opensource/releases.md).

## Security

Do not open public issues for vulnerabilities. See [SECURITY.md](SECURITY.md).

## Questions

Open a [GitHub Discussion](https://github.com/AION-by-ASA-Computer/AION_Agent/discussions) or an issue with the `question` label.

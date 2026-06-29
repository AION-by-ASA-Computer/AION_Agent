# AION Agent

Self-hosted AI agent platform with MCP tool integration, multi-level memory (STM/LTM),
YAML profiles, skills, and Plan Mode for structured multi-step work.

[![CI](https://github.com/AION-by-ASA-Computer/AION_Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/AION-by-ASA-Computer/AION_Agent/actions/workflows/ci.yml)

**Commercial site:** [https://aion-asa.com](https://aion-asa.com) · **Italian README:** [README.it.md](README.it.md)

## Features

| Area | Description |
|------|-------------|
| **Chat UI** (`chat-ui/`) | Primary Next.js client: SSE streaming, attachments, plan dock |
| **Admin UI** (`admin-ui/`) | Profiles, users, memory, agent DB management |
| **MCP tools** | Dynamic stdio/SSE tools; registry in `config_std/mcp_registry.yaml` |
| **Memory** | STM window, LTM extraction (MemPalace), SQLite + FTS history |
| **Profiles & skills** | YAML profiles; Markdown skills with frontmatter |
| **Plan Mode** | Tool-first plans, human approval, background execution |
| **Docker** | Production stack with Caddy path routing; dev compose with hot reload |

## Prerequisites

- **Python 3.13+**
- **[uv](https://github.com/astral-sh/uv)** (recommended) or `venv` + `pip`
- **[pnpm](https://pnpm.io/) 9+** (for `chat-ui`, `admin-ui`, `website`)
- **OpenAI-compatible LLM** (Ollama, vLLM, LiteLLM, cloud API)

## Quick start (local, ~10 minutes)

### 1. Clone and configure

```bash
git clone https://github.com/AION-by-ASA-Computer/AION_Agent.git
cd AION_Agent

cp .env.example .env
# Required: set your LLM endpoint
#   AION_API_URL=http://localhost:11434/v1    # Ollama example
#   AION_MODEL=llama3.2
#   AION_LLM_API_KEY=placeholder-token         # or your provider key

./scripts/setup-aion-env.sh
```

`setup-aion-env.sh` syncs `config_std/` → `config/` and `mcp_servers_std/` → `mcp_servers/`.
The API **refuses to start** without `AION_API_URL` set.

Generate secrets for production:

```bash
openssl rand -hex 32   # AION_CHAT_AUTH_SECRET (if chat password auth enabled)
```

### 2. Install backend dependencies

```bash
uv venv && uv pip install -r requirements.txt
# Optional: uv pip install pytest pytest-asyncio ruff
```

### 3. Run services

**Terminal 1 — API (port 8001, single worker required):**

```bash
uvicorn src.api.main:app --reload --reload-exclude data/sessions
```

**Terminal 2 — Chat UI (port 8003):**

```bash
cd chat-ui && pnpm install && pnpm dev
```

Open http://localhost:8003

**Optional — Admin UI (port 3870):**

```bash
cd admin-ui && pnpm install && pnpm dev --webpack
```

### Default credentials

When admin auth is enabled (default): **`admin` / `admin`** — change password on first login.

Chat auth is optional (`AION_CHAT_PASSWORD_AUTH=0` opens chat without login; useful for local dev).

## Docker

### Local full stack (HTTP, no domain)

```bash
cp .env.example .env
# Edit AION_API_URL, DOMAIN=:80, and LLM settings (see DEPLOY DOCKER section in .env.example)
./scripts/setup-aion-env.sh --docker
docker compose up -d --build
```

| URL | Service |
|-----|---------|
| http://localhost/ | Chat UI |
| http://localhost/admin | Admin UI |
| http://localhost/docs/ | Documentation |
| http://localhost/api/health | Backend health |

### Development compose (API + chat-ui + Redis, hot reload)

```bash
docker compose -f docker-compose.dev.yml up
```

Details: [docs/deployment/docker.md](docs/deployment/docker.md)

## Project layout

```text
src/              FastAPI backend, agent pipeline, memory, MCP manager
chat-ui/          Primary Next.js chat client
admin-ui/         Admin dashboard (Next.js)
website/          Docusaurus docs site
config_std/       Committed config templates (synced to config/ at setup)
mcp_servers_std/  Committed MCP server sources
docs/             Documentation source of truth
data/             Runtime data (gitignored; eval fixtures whitelisted)
```

See [docs/architecture/source-tree.md](docs/architecture/source-tree.md).

## Development

```bash
# Curated CI test suite (no live LLM)
./scripts/run_ci_tests.sh

# Full test tree (many tests need .env / mocks)
python -m pytest src/test/ -v

# Lint
uv run ruff check --config ruff.toml src/
uv run ruff format --check --config ruff.toml src/

# Ensure data/ runtime files are not tracked
python scripts/check_data_git_tracking.py
```

**Constraints:**

- Backend must run with **one worker** (`--workers 1`); in-process MCP pools and agent cache are not multiprocess-safe.
- Use **pnpm** in JS packages (not npm/yarn).
- Import `src.aion_env` before reading `os.environ` in scripts.

Assistant onboarding: [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Open PRs against **`main`** on this repository.

The private **AION_Agent_V1** repo is an archived snapshot only — do not use it for new work. See [docs/opensource/repository-model.md](docs/opensource/repository-model.md).

## Documentation

Rendered site: build from `website/` or read sources in `docs/`.

| Topic | Path |
|-------|------|
| Architecture | [docs/architecture/](docs/architecture/) |
| Configuration / env | [docs/configuration/](docs/configuration/) |
| API & runtime | [docs/api-and-runtime/](docs/api-and-runtime/) |
| MCP | [docs/mcp/](docs/mcp/) |
| Security | [docs/security/](docs/security/) |

## Telemetry

OpenTelemetry and Opik hooks exist but are **off by default** (`AION_OTEL_ENABLED=0`). No phone-home analytics in the default configuration.

## Security

Report vulnerabilities privately — [SECURITY.md](SECURITY.md).

## License

[Apache License 2.0](LICENSE). Third-party notices: [NOTICE](NOTICE).

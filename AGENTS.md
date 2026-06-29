# AGENTS.md

Compact guidance for AI coding assistants working in this repository.
See also `CLAUDE.md` for the full developer quickstart.

## Monorepo layout (3 packages + 1 backend)

```
src/           Python backend (FastAPI, Haystack agent, MCP)
admin-ui/      Next.js admin dashboard (pnpm workspace)
chat-ui/       Next.js chat client — primary UI (pnpm workspace)
website/       Docusaurus documentation site (pnpm workspace)
```

Use **pnpm** for JS packages — never npm/yarn. `pnpm-lock.yaml` is gitignored.
Workspace root `package.json` has no scripts — run from inside each package directory.

## Python: environment loading is mandatory and order-sensitive

`src/aion_env.py` loads `.env` from the repo root. **It must be imported before any
other module that reads `os.environ`**:

```python
import src.aion_env  # noqa: F401 — MUST be first import
```

Config YAML files (e.g. `config/default.yaml`) support `${ENV_VAR}` substitution
via `src/config.py`. The `config/` directory is in `.gitignore` — the committed
source of truth is `config_std/`. Setup scripts sync `config_std/` → `config/`.

All application env vars are prefixed `AION_`. The full template is `.env.example`.

## Running locally

```bash
# Python backend (port 8001)
uvicorn src.api.main:app --reload --reload-exclude data/sessions
# OR:  python -m src.api.main   (reads AION_API_RELOAD=1 for reload)

# Chat UI (port 8003)
cd chat-ui && pnpm dev

# Admin UI (port 3870) — note the --webpack flag
cd admin-ui && pnpm dev

# Docs site
cd website && pnpm start
```

## Backend: single-worker constraint

The FastAPI server **must run with `--workers 1`**. In-process state (agent cache,
`TOOL_EVENT_QUEUE`, per-session MCP stdio pools) does not survive multiprocess
fan-out. If horizontal scaling is needed, use sticky sessions at the reverse proxy.

## Auth: two separate layers

- **Chat auth** (`AION_CHAT_PASSWORD_AUTH`): controls whether chat-ui requires login.
  Uses HMAC tokens, shared users table in the unified DB (`src/chat_auth.py`).
- **Admin auth** (`AION_ADMIN_PASSWORD_AUTH`): always on by default (Grafana-style).
  Controls `/admin/*` endpoints. Separate from chat auth.

Legacy env aliases (`AION_CHAINLIT_*`, `CHAINLIT_AUTH_SECRET`) are deprecated;
new names (`AION_CHAT_*`) take precedence. The upgrade script
(`scripts/upgrade-aion.sh`) auto-migrates them.

## MCP tool registration

MCP tools are serialized via Haystack `Tool.to_dict()` → **must be top-level
functions**, not bound methods. Registry merge: `config/mcp_registry.yaml` (base,
committed) + optional `config/mcp_registry.local.yaml` (local override, gitignored).

MCP servers run as subprocesses via stdio. `AION_MCP_POOL=1` keeps persistent
connections per chat session.

## Database: unified SQLite + Alembic

Single database at `data/aion.db` (SQLite via aiosqlite + SQLAlchemy).
Migrations in `migrations/versions/`. Run them with Alembic (configured in
`alembic.ini`). Redis is optional (`AION_REDIS_URL`), with an in-process fallback.

Agent DB is a separate per-user SQLite under `data/agent_dbs/<tenant>/<user>.db`.

## Session management

Sessions are indexed by `(session_id, profile_name, user_id)`. MCP tools are
cached per session. Sandbox files live in `data/sessions/<session_id>/` (gitignored).

## Next.js: version-specific quirks

Both `chat-ui` and `admin-ui` use **Next.js 16.2.3** with **React 19.2.4**.
The `admin-ui` dev command requires `--webpack` (not Turbopack):
`next dev --webpack -p 3870`.

Each frontend has its own `AGENTS.md` instructing to consult
`node_modules/next/dist/docs/` before writing code — Next.js 16 has breaking
changes from the versions most LLMs were trained on.

## Testing

```bash
python -m pytest src/test/ -v
# single file:
python -m pytest src/test/test_memory.py -v
```

Tests live in `src/test/`. Many require a running backend and `.env` loaded.

## Key conventions

- **Kebab-case** for file names (both Python modules and docs): `agent-pipeline.py`,
  `chat-history-and-fts.md`.
- **Frontmatter required** in all Markdown docs: `title`, `sidebar_position`,
  `description`.
- **Docs single source of truth**: `docs/` directory; rendered by `website/` (Docusaurus).
- **API paths** use `/v1/` prefix (e.g., `/chat`, `/profiles`).
- **Profiles** live in `config_std/profiles/` as YAML files.
- **Skills** are Markdown files with YAML frontmatter loaded by `src/skill_registry.py`.

## Docker notes

- Production: `docker compose up -d --build` with `.env` from `.env.example` (see DEPLOY DOCKER section)
- Dev compose (`docker-compose.dev.yml`): backend + chat-ui + redis with hot reload
  and the same `*_std` → runtime sync at boot as production.
- Production Dockerfiles live in `docker/` (multi-stage, uv-based). The root
  `Dockerfile` is a legacy single-stage build kept for backward compatibility.
- Caddy reverse proxy handles path-based routing and auto-TLS in production.

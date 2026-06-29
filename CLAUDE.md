# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start Commands

```bash
# Setup environment (from repo root)
cp .env.example .env                          # Copy environment template
# Edit .env with your LLM URL, API keys, and other settings

# Start FastAPI backend (port 8001)
uvicorn src.api.main:app --reload \
  --reload-exclude data/sessions
# Or: python -m src.api.main

# Start Chat UI Next.js (port 8003) — primary client
cd chat-ui && npm run dev

# Start Admin UI (port 3870)
cd admin-ui && npm run dev

# Build documentation site (from website/)
cd website && npm run build
cd website && npm run start
```

## Docker Quickstart

The repository ships with a full Docker stack for multi-tenant deployment:
single domain + path-based routing via Caddy reverse proxy (auto-HTTPS via
Let's Encrypt). One DNS A record per customer is sufficient.

### Two supported scenarios

**A) Local (HTTP, no domain required)** — just spin up the full stack on your
laptop without DNS or TLS:

```bash
cp .env.docker.example .env   # DOMAIN=:80 by default => Caddy serves HTTP/80
docker compose up -d --build
# http://localhost  /  http://localhost/admin  /  http://localhost/docs/  /  http://localhost/api/health
```

**B) Production (real customer, auto-HTTPS via Let's Encrypt)**:

```bash
# 1. Copy and edit the Docker .env
cp .env.docker.example .env
vim .env   # set DOMAIN=cliente.example.com, LETS_ENCRYPT_EMAIL=..., secrets,
           # AION_PUBLIC_API_URL=https://${DOMAIN}/api, AION_CORS_ORIGINS=https://${DOMAIN}

# 2. Build + start the full stack
docker compose up -d --build

# 3. Verify
docker compose ps
docker compose logs -f caddy backend
```

After Caddy provisions the TLS certificate (~30s on first start), the
customer accesses:

| Path                        | Service             | Container port |
|-----------------------------|---------------------|----------------|
| `https://${DOMAIN}/`        | chat-ui Next.js     | 8003           |
| `https://${DOMAIN}/admin`   | admin-ui Next.js    | 3870 (`basePath=/admin`) |
| `https://${DOMAIN}/docs/`   | website Docusaurus  | 3000 (nginx, `baseUrl=/docs/`) |
| `https://${DOMAIN}/api/*`   | backend FastAPI     | 8001 (prefix stripped by Caddy) |

Backend and frontends communicate via the internal `aion_net` bridge network.
The customer's browser only sees ports 80/443 on Caddy.

### Development stack (essenziali)

For day-to-day development, only API + chat-ui + Redis are containerised;
`admin-ui` and `website` remain runnable via `npm run dev` as today.

```bash
docker compose -f docker-compose.dev.yml up
# backend  -> http://localhost:8001 (hot reload via src/ bind mount)
# chat-ui  -> http://localhost:8003 (next dev via chat-ui/ bind mount)
# redis    -> 127.0.0.1:6379

# In parallel, when needed:
cd admin-ui && npm run dev   # http://localhost:3870
cd website  && npm run start # http://localhost:3000
```

### Onboarding a new customer

1. `git clone` the repo on the customer's server
2. `cp .env.docker.example .env` and set `DOMAIN`, `AION_API_URL`, secrets
3. Create one DNS `A` record pointing to the server
4. `docker compose up -d --build`
5. Caddy obtains the Let's Encrypt certificate automatically

### Docker file layout

```
docker/
├── Dockerfile.backend     # Python 3.13 + tesseract + poppler (FastAPI + MCP)
├── Dockerfile.chat-ui     # Next.js standalone (output: 'standalone')
├── Dockerfile.admin-ui    # Next.js standalone + basePath=/admin
├── Dockerfile.website     # Docusaurus build + nginx static
├── Caddyfile              # path-based routing with SSE-friendly /api/*
└── nginx-website.conf     # static asset serving for Docusaurus

docker-compose.yml         # production: caddy + 4 apps + redis
docker-compose.dev.yml     # dev: backend + chat-ui + redis (with hot reload)
.dockerignore              # excludes .venv, node_modules, data/, *.db, build/
.env.docker.example        # Docker-specific env template (DOMAIN + AION_* overrides)
```

### Operational notes

- **Backend workers**: `--workers 1` is mandatory. In-process state (agent
  cache, `TOOL_EVENT_QUEUE`, per-session MCP stdio pools) does not survive
  fan-out. Horizontal scale requires sticky sessions on Caddy.
- **Persistent volumes**: `aion_data` (SQLite, sessions, profiles, generated
  skills), `caddy_data` (certs), `redis_data`. Backup with
  `scripts/aion_backup.py` from inside the backend container.
- **Docs URL caveat**: with `DOCUSAURUS_BASE_URL=/docs/` the build keeps
  `routeBasePath=docs` (default), so deep doc URLs become
  `/docs/docs/<page>`. To collapse the prefix, set `routeBasePath: '/'` in
  `website/docusaurus.config.ts` and remove `website/src/pages/index.tsx`
  to avoid the homepage route collision.
- **SSE / streaming**: Caddy is configured with `flush_interval -1` and
  unlimited timeouts on `/api/*` for the `/chat` SSE endpoint.

## Project Structure

```
AION_Agent/
├── src/                          # Core Python backend
│   ├── api/                      # FastAPI endpoints
│   │   ├── main.py              # Main API: /chat (SSE), /profiles, /health, /admin/*
│   │   ├── history.py           # Chat history with SQLite + FTS5 full-text search
│   │   └── admin.py             # Admin endpoints for profiles, memory management
│   ├── memory/                   # Memory management modules
│   │   ├── ltm_orchestrator.py  # Long-term memory: MemPalace integration, JSON extraction
│   │   ├── stm_consolidator.py  # Short-term memory consolidation, pruning
│   │   ├── llm_extract.py       # LLM-based extraction via HTTP (vLLM/OpenAI-compat)
│   │   ├── context_compressor.py# Context compression for STM
│   │   └── chat_memory.py       # SQLite schema, session indexing
│   ├── learning/                 # Hermes learning features
│   │   ├── skill_distiller.py   # Distills tool usage into reusable skills
│   │   ├── nudge.py             # Prompts users for engagement
│   │   ├── skill_patcher.py     # Skill patching/updates
│   │   └── dedup.py             # Skill deduplication
│   ├── tools/                    # MCP tool wrappers
│   │   ├── prometheus_tools.py  # Prometheus query tools
│   │   ├── grafana_tools.py     # Grafana dashboard tools
│   │   └── session_code.py      # Session sandbox execution
│   ├── mcp_manager.py            # MCP stdio pool, registry merge, tool discovery
│   ├── main.py                   # Agent factory: get_agent(), Tool registration
│   ├── agent_pipeline.py         # Streaming pipeline: STM/LTM, compression, events
│   ├── agent_profile.py          # Profile YAML loading, system prompt generation
│   ├── skill_registry.py         # Markdown skill loading with frontmatter
│   ├── haystack_chat.py          # ChatMessage helpers
│   ├── config.py                 # Default config with ${VAR} substitution
│   ├── aion_env.py               # .env loading before other imports
│   └── identity.py               # User ID sanitization
│
├── mcp_servers/                  # Custom MCP servers
│   └── ocr_mcp/                  # OCR server (GLM-OCR model)
│
├── config/                       # Configuration files
│   ├── profiles/                 # Agent profiles (YAML)
│   │   ├── aion_std.yaml        # Standard assistant profile
│   │   └── *.yaml               # Other predefined profiles
│   ├── mcp_registry.yaml        # MCP server definitions (committable)
│   └── default.yaml             # Default config values
│
├── src/api/                      # FastAPI REST endpoints
│   ├── main.py                  # Main server: /chat SSE, /profiles, /admin/*
│   ├── history.py               # Chat history API with STM window
│   ├── admin.py                 # Admin: profile management, audit logs
│   └── session_uploads.py       # File upload handling
│
├── admin-ui/                     # Next.js admin dashboard
│   ├── src/                     # React components (TypeScript)
│   └── package.json
│
├── chat-ui/                      # Next.js primary chat client (port 8003)
│   ├── app/                     # App Router
│   └── package.json
│
├── website/                      # Docusaurus documentation site
│   ├── src/                     # MDX pages
│   └── package.json
│
├── docs/                         # Source documentation (single source of truth)
│   ├── architecture/            # Architecture overview, source-tree
│   ├── configuration/           # Environment, profiles, skills, SOUL/MEMORY/USER
│   ├── api-and-runtime/         # REST API spec, agent pipeline details
│   ├── clients/                 # chat-ui and admin UI docs
│   ├── memory/                  # STM/LTM/QueryMemory architecture
│   ├── mcp/                     # MCP registry and protocol
│   ├── security/                # Identity and chat authentication
│   ├── learning/                # Hermes feature documentation
│   └── standard/                # Authoring guidelines
│
├── data/                         # Runtime data (in .gitignore)
│   ├── chat_memory.db           # SQLite chat history
│   └── sessions/                # Session workspace, sandbox files
│
├── .env.example                  # Environment variable template
└── docker-compose.yml            # Docker setup for haystack-agent
```

## Core Architecture

### Request Flow
```
Client (chat-ui / browser) ──► FastAPI (/chat SSE) ──► AgentPipeline
    │                                                           │
    │                                                           ▼
    │                                               Haystack Agent + MCP Tools
    │                                                           │
    │                                                           ▼
    │                                               vLLM/OpenAI-compatible LLM
    │                                                           │
    ▼                                                           ▼
SQLite (history/FTS)                                 MCP stdio pools per session
```

### Key Components

| Component | Path | Responsibility |
|-----------|------|----------------|
| Agent Factory | `src/main.py` | Creates Haystack Agent with MCP tools, caches by (session, profile, user) |
| Pipeline | `src/agent_pipeline.py` | Streams tokens, handles STM window, compression, LTM extraction, nudge/distill |
| MCP Manager | `src/mcp_manager.py` | Manages stdio pools, tool discovery, registry merge |
| Profile Manager | `src/agent_profile.py` | Loads YAML profiles, generates system prompts with SOUL/MEMORY/USER |
| LTM Orchestrator | `src/memory/ltm_orchestrator.py` | Long-term memory extraction, context retrieval, MemPalace integration |
| History Manager | `src/api/history.py` | SQLite storage with FTS5, STM window queries |
| Skill Registry | `src/skill_registry.py` | Markdown skill files with frontmatter, generated skills folder |

### MCP Integration

MCP (Model Context Protocol) servers provide dynamic tool discovery. Key behavior:
- **Pool mode** (`AION_MCP_POOL=1`): Persistent stdio connection per chat session
- Registry merge: Base `config/mcp_registry.yaml` + optional overlay `config/mcp_registry.local.yaml`
- Tools serialized via Haystack `Tool.to_dict()` → requires top-level functions (no bound methods)

### Memory Management

**STM (Short-Term Memory)**:
- Configurable window via `AION_STM_MAX_TURNS`, `AION_STM_TOKEN_BUDGET`
- Consolidation triggers every N turns (`AION_STM_CONSOLIDATE_EVERY`)
- Pruning after consolidation (`AION_STM_PRUNE_KEEP`)

**LTM (Long-Term Memory)**:
- Extraction after each turn via `ltm_orchestrator.extract_and_persist()`
- JSON extraction with `AION_LTM_JSON_RESPONSE_FORMAT`
- Context retrieval prefixed to user messages

**Context Compression**:
- Enabled by `AION_CONTEXT_COMPRESS_ENABLED=1`
- Compresses STM when threshold exceeded (`AION_CONTEXT_COMPRESS_THRESHOLD=0.5`)

## Environment Variables

All variables prefixed with `AION_` are read from `os.environ`. Critical ones:

| Variable | Default | Description |
|----------|---------|-------------|
| `AION_API_URL` | `http://...:8000/qwen3/v1` | LLM endpoint (vLLM) |
| `AION_API_PORT` | `8001` | FastAPI port |
| `AION_CHAT_MAX_TOKENS` | `8192` | Max response tokens |
| `AION_LTM_RETRIEVAL` | `1` | Enable LTM retrieval |
| `AION_MCP_POOL` | `1` | Persistent MCP stdio pool |
| `AION_SKILL_SYSTEM_PROMPT_MODE` | `index` | Skill inclusion mode |
| `AION_SOUL_MEMORY_USER_SPLIT` | `1` | Include SOUL/MEMORY/USER in prompt |

See `.env.example` for full list with comments.

## Development Notes

### Debugging Tool Events
Tool events (start/end/error) are emitted via `TOOL_EVENT_QUEUE` in `src/main.py`. These are accessible from `src/agent_pipeline.py` during streaming.

### Session Management
- Sessions indexed by `(session_id, profile_name, user_id)`
- MCP tools cached per session to avoid re-discovery
- Sandbox files written to `data/sessions/<session_id>/`

### Testing
- Tests live in `src/test/` (e.g., `test_memory.py`, `test_search.py`)
- Run tests with: `python -m pytest src/test/ -v`

### Chat auth (chat-ui)

Password auth for chat-ui uses the unified `users` table and HMAC tokens (`src/chat_auth.py`).

**Modern variable names (use these):**
| Variable                       | Purpose                                                 |
|--------------------------------|---------------------------------------------------------|
| `AION_CHAT_PASSWORD_AUTH=1`    | Enable password auth (else open chat)                   |
| `AION_CHAT_AUTH_SECRET`        | JWT secret for `/auth/login` tokens (32+ chars)         |
| `AION_SETUP_CHAT_IDENTIFIER`   | First admin username (only `-y` / `--import-state`)     |
| `AION_SETUP_CHAT_PASSWORD`     | First admin password (only `-y` / `--import-state`)     |

**Legacy aliases (deprecated, read as fallback):**
`AION_CHAINLIT_PASSWORD_AUTH`, `CHAINLIT_AUTH_SECRET`, `AION_SETUP_CHAINLIT_IDENTIFIER`,
`AION_SETUP_CHAINLIT_PASSWORD`. The new names take precedence; the old names
will be removed in a future release. **Automatic migration** of a legacy `.env`:

```bash
./scripts/upgrade-aion.sh           # invoca _migrate_env_legacy_keys()
./scripts/upgrade-aion.sh --docker  # idem in flusso Docker
./scripts/upgrade-aion.sh --dry-run # mostra cosa cambierebbe senza scrivere
```

**Storage:**
- Users live in the ORM table `users` (DB unificato, `AION_DB_URL`,
  default `data/aion.db`).
- Chat persistence uses the same unified schema (`conversations`, `messages`, …).

**Provisioning users:**
- Setup wizard: `./scripts/setup-aion-env.sh` (interactive, or automated via `AION_SETUP_CHAT_IDENTIFIER` / `AION_SETUP_CHAT_PASSWORD`)
- REST: `POST /admin/users` (admin API) or via Next.js Admin UI dashboard
- Manual SQL: hash with `python -m src.chat_auth hash`

Generate the auth secret with `openssl rand -hex 32`.

### Admin auth (always on, Grafana-style)

The `/admin/*` router is **always protected** independent of chat auth:

| Variable                              | Default | Purpose                                                       |
|---------------------------------------|---------|---------------------------------------------------------------|
| `AION_ADMIN_PASSWORD_AUTH`            | `1`     | `0` opens `/admin/*` (dev escape hatch only)                  |
| `AION_SETUP_ADMIN_BOOTSTRAP`          | `1`     | Bootstrap a default admin if none exists                      |
| `AION_SETUP_ADMIN_DEFAULT_IDENTIFIER` | `admin` | Default admin username                                        |
| `AION_SETUP_ADMIN_DEFAULT_PASSWORD`   | `admin` | Default admin password (must change at first login)           |

- `require_admin_role` in `src/api/auth_login.py` enforces Bearer token + role
  `admin` on every `/admin/*` endpoint.
- The user model has a `users.roles` JSON-list column and a
  `users.must_change_password` flag (migration `d1a23b4f0001`).
- The chat token is HMAC-signed with `user_row_id:identifier:roles_csv:exp:sig`
  (backward-compatible with the legacy 3-field form).
- First-login flow (admin-ui + chat-ui): non-blocking `/change-password`
  banner. Skip key in localStorage:
  `aion_admin_change_pw_skipped_until` (24h).

See [`docs/clients/admin-ui.md`](docs/clients/admin-ui.md#admin-auth-always-on)
for the full design.

### Documentation
- Single source of truth: `docs/` directory
- Rendered site: `website/` (Docusaurus)
- Authoring guidelines: `docs/standard/authoring.md`

## Known Conventions

- Kebab-case for file names: `agent-pipeline.md`, `chat-history-and-fts.md`
- Frontmatter required in MD files: `title`, `sidebar_position`, `description`
- Mermaid diagrams supported in docs
- API paths use `/v1/` prefix (e.g., `/chat`, `/profiles`)

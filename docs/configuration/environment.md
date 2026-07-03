---
sidebar_position: 1
title: Environment and Config - Philosophy and Trade-off
description: Why variables are categorized, performance trade-offs, and when to modify each setting.
---

# Environment and Config Files

## Philosophy of the configuration system

### Why three configuration levels?

The system uses **three levels** to balance security, versioning, and local flexibility:

1. **`.env` (Environment Secrets):** Secrets, URLs, credentials. Not committable, specific to each installation.
2. **`config_std/` (Standard Templates):** Structured configurations, base profiles, and curated skills. It is the **versioned source of truth** (committable).
3. **`config/` (Active Local Config):** The operational directory read by the agent. It is **ignored by Git** and is automatically populated from `config_std/` during setup.

**Why this design:**
- **Security:** `.env` and `config/` (which can contain sensitive data like user password hashes) are never uploaded to Git.
- **Easy Initialization:** `scripts/sync_config.py` (integrated in `setup-aion-env.sh`) creates the local configuration starting from the standard templates. With `--prepare-runtime`, `runtime_extras_setup` also copies the `fs_policy` templates and can install Playwright for the MCP promo (see [filesystem-policy-and-promo](./filesystem-policy-and-promo.md)).
- **Conflict-free customization:** You can modify files in `config/` or add new local profiles/skills without dirtying the Git repository or having conflicts during a `git pull`.
- **`${VAR}` Substitutions:** YAML supports `${VAR}` to insert `.env` variables into project YAML values.

---

## Categorization of variables

The `AION_*` variables are divided into **functional categories**, not by priority or importance.

### 🔴 Critical Variables (System does not function without)

These variables are **essential** for basic functioning:

| Variable | Default | Why it is critical |
|-----------|---------|------------------|
| `AION_API_URL` | `http://...:8000/qwen3/v1` | LLM model URL - without LLM, no chat |
| `AION_MODEL` | `AIONQ35-35-Q8B` | Model to use - different model = different behavior |
| `AION_UNIFIED_DB` | `1` | Enables the use of the unified DB `aion.db` (F1) |
| `AION_API_PORT` | `8001` | API port - clients must connect here |

### 🟡 Performance and Infrastructure Variables (V2)

These variables configure the shared state and storage:

| Variable | Default | Description |
|-----------|---------|-------------|
| `AION_REDIS_URL` | `redis://localhost:6379/0` | Redis URL for rate limit, locks, and chart queue |
| `AION_REDIS_FALLBACK_LOCAL` | `1` | If `1`, use in-process implementations if Redis is offline |
| `AION_STORAGE_BACKEND` | `local` | `local` (filesystem) or `s3` (AWS/MinIO/RustFS) |
| `AION_STORAGE_LOCAL_ROOT` | `data` | Root directory for local storage |
| `AION_STORAGE_S3_BUCKET` | `aion-sessions` | S3 bucket to use if backend=s3 |
| `AION_SESSION_CACHE_MAX_GB` | `5` | Local cache budget for files downloaded from S3 storage |

### 🟢 Feature Gates and Hermes Variables

These variables **enable/disable** advanced features:

| Variable | Default | When to enable |
|-----------|---------|------------------|
| `AION_APPROVAL_ENABLED` | `1` | You want control over critical tools (shell/python) |
| `AION_APPROVAL_LEARN` | `1` | Learn from user approvals (smart rules) |
| `AION_PLUGINS_ENABLED` | `1` | Allows loading plugins from `data/plugins/` |
| `AION_PII_REDACT` | `1` | Enables redacting sensitive data from messages |
| `AION_CONTEXT_COMPRESS_ENABLED` | `1` | Auto-compact STM before `agent.run` (mandatory for long chats) |
| `AION_MODEL_MAX_CONTEXT` | `131072` | Align with LLM model limit |
| `AION_CONTEXT_COMPRESS_RESERVE_OUTPUT` | `1` | Reserve `AION_CHAT_MAX_TOKENS` to avoid 400 context length errors |
| `AION_SKILL_DISTILL_ENABLED` | `1` | Automatic generation of skills from usage patterns |
| `AION_SKILL_DISTILL_TOOL_LOG_MAX_CHARS` | `8000` | TOOLS section in the distill prompt (tool_start/end/error sequence) |
| `AION_SKILL_VIEW_METRICS` | `1` | `skill_view` counter in `data/logs/skill_view_metrics.jsonl` |
| `AION_SKILL_VIEW_ENFORCE_PROFILE` | `1` | `skill_view` / `skill_list` only for skills in `profile.skills` |
| `AION_DEFAULT_PROFILE` | `aion_std` | Profile slug if the request does not specify a valid one |
| `AION_PROFILE_VALIDATE_STRICT` | `0` | API boot fails on invalid YAML profiles |
| `AION_PROFILE_HOT_RELOAD` | `0` | Reload profiles from mtime at each `get_agent` (dev) |
| `AION_PROFILE_LEGACY_NAME_LOOKUP` | `0` | Profile lookup by display name (legacy) |
| `AION_MCP_POOL` | `1` | Persistent stdio pool (via `src/settings.py`) |
| `AION_MCP_SESSION_ENV_INJECT` | `0` | Inject parent env for call_tool (legacy; prefer session-scoped pool) |
| `AION_MCP_SESSION_SCOPED_SERVERS` | *(CSV)* | Servers with pool for `chat_session_id` |
| `AION_MEMPALACE_NAV_ENABLED` | `1` | Inject/search ERP navigation on `wing_proj_{project}` |
| `AION_MEMPALACE_NAV_AUTO_LEARN` | `0` | Auto-drawer post_tool (disabled: agent tools only) |
| `AION_MEMPALACE_NAV_SKIP_WHEN_SQL_INJECT` | `1` | Skip MemPalace pre_turn search if QueryMemory has already injected SQL |
| `AION_SQL_QM_AUTO_LEARN` | `0` | Auto-save SQL post_tool (disabled: agent `sql_memory_save` only) |
| `AION_MEMPALACE_NAV_AUTO_KG` | `0` | After multi-table SELECT, `mempalace_kg_add` `joins_via` |
| `AION_MEMPALACE_PALACE_PATH` | *(auto)* | Root palace; default `data/mempalace/{tenant_id}/` → `MEMPALACE_PALACE_PATH` |
| `AION_LTM_MIN_IMPORTANCE` | `2` | LTM extraction: ignore drawer with `importance` below threshold |
| `AION_LTM_EXTRACT` | `1` | Enable `extract_and_persist` post-turn (equivalent to MemPalace hook) |
| `AION_AGENT_MIN_REASONING_CHARS_WITHOUT_TOOL` | `6000` | SSE `turn_status` if many reasoning characters without tool (0=off) |
| `AION_AGENT_MAX_REASONING_WITHOUT_TOOL` | `0` | Optional: threshold on SSE reasoning chunk (0=ignore; prefer chars) |
| `AION_REASONING_HARD_STOP` | `0` | If `1`, interrupts the turn when it exceeds **both** `AION_REASONING_MAX_*` (not recommended: empty response) |
| `AION_SQL_QM_PARAMETERIZE` | `1` | Literals → `?` before save SQL QueryMemory |

### 🔵 Observability and Telemetry Variables (V3)

These variables configure tracking, metrics, and structured logging:

| Variable | Default | Description |
|-----------|---------|-------------|
| `AION_ENV` | `dev` | Environment label (`dev` / `staging` / `prod`) propagated in trace/log |
| `AION_OTEL_ENABLED` | `0` | Enables OpenTelemetry tracing |
| `AION_OPIK_ENABLED` | `0` | Enables Opik (Comet ML) LLM telemetry tracing |
| `AION_OTEL_ENDPOINT` | `http://localhost:4317` | gRPC/HTTP endpoint of the OTel collector |
| `AION_OTEL_PROTOCOL` | `grpc` | Protocol to the collector (`grpc` or `http/protobuf`) |
| `AION_OTEL_SERVICE_NAME` | `aion-agent` | Service name reported in traces |
| `AION_METRICS_ENABLED` | `1` | Enables the Prometheus endpoint `/metrics` |
| `AION_METRICS_PATH` | `/metrics` | Path of the Prometheus endpoint |
| `AION_LOG_FORMAT` | `json` | Log format (`json` or text) for integration with Loki/ELK |
| `AION_PROFILING_ENABLED` | `1` | Per-turn profiling (pipeline timing events) |
| `AION_PROFILING_STORAGE` | `jsonl` | Profiling storage backend (`jsonl`, `sqlite`, `redis`) |
| `AION_PROFILING_JSONL_DIR` | `data/profiling` | JSONL records folder (Docker volume: `/app/data/profiling`) |

### 🟣 Per-turn runtime guardrails

Hard limits on the single turn to avoid LLM runaway loops:

| Variable | Default | Description |
|-----------|---------|-------------|
| `AION_REASONING_MAX_CHARS` | `0` | Max characters of streamed reasoning (0 = no cap; recommended for SQL) |
| `AION_REASONING_MAX_EVENTS` | `0` | Max reasoning events per turn (0 = no cap) |
| `AION_TOOL_CALLS_MAX_PER_TURN` | `24` | Hard cap on tool calls |
| `AION_TOOL_EVENTS_MAX_PER_TURN` | `60` | Hard cap on emitted tool events |
| `AION_TOOL_DEDUPE_ENABLED` | `1` | Deduplicates identical tool calls close in time (loop guard) |
| `AION_TOOL_DEDUPE_TTL_SEC` | `20` | Deduplication TTL window |
| `AION_TTC_MAX_ATTEMPTS` | `3` | Test-Time Compute: max retries per turn |
| `AION_TTC_MAX_TOKENS` | `10000` | Overall TTC token budget per turn |
| `AION_ORCH_TOOL_TIMEOUT_SEC` | `900` | Execution timeout of a single tool from orchestration |

### ⚙️ Auth & admin

| Variable | Default | Description |
|-----------|---------|-------------|
| `AION_CHAT_AUTH_TOKEN_TTL_SEC` | `604800` | chat-ui JWT token TTL (7 days) |
| `AION_AGENT_DB_ADMIN_SQL_WRITE` | `0` | Enables SQL write on admin agent-db (risky in prod) |
| `AION_AGENT_DB_ADMIN_STRICT_IDENTITY` | `1` | Requires X-AION-Identity consistent with session |
| `AION_AGENT_DB_EMBED_SECRET` |  | Secret HMAC embedded token /agent-db |
| `AION_FS_POLICY_PATH` |  | Filesystem policy YAML path (empty = default in-code) |
| `AION_PROMO_CAPTURE_ENABLED` | `1` | Enables PNG export via MCP `promo_render` |
| `AION_PROMO_CAPTURE_TIMEOUT_MS` | (optional) | Playwright capture timeout (ms) |
| `AION_ADMIN_UI_URL` | `http://localhost:3870` | admin-ui public URL (for Chat UI banner) |

Operational guide (templates `config/fs_policy*.yaml`, Playwright, setup/upgrade flags):
[Filesystem policy and promo PNG export](./filesystem-policy-and-promo.md).

---

## Deploy via Docker Compose

For containerized deployment (stack `caddy + backend + chat-ui + admin-ui + website + redis`)
a **`.env`** file derived from `.env.docker.example` is used instead of `.env.example`.

> **Note:** an `.env.docker` file in the root is **not** read by `docker-compose.yml` (only `.env`).
> If it exists, it is a local duplicate: align the variables in `.env` or delete it.

The following keys are read only by Compose/Caddy (not by Python code):

| Variable             | Example                   | Description                              |
|-----------------------|---------------------------|------------------------------------------|
| `DOMAIN`              | `cliente.example.com`     | Public hostname; `:80` for dev HTTP    |
| `LETS_ENCRYPT_EMAIL`  | `ops@aion-asa.com`        | ACME Let's Encrypt contact              |
| `REDIS_PASSWORD`      | _(optional)_             | If valued, Redis requires auth      |
| `NEXT_PUBLIC_AION_API_URL` | `/api`               | Baked in chat-ui/admin-ui at build time   |
| `NEXT_PUBLIC_AION_ADMIN_UI_URL` | `/admin`        | Link chat-ui → admin-ui                  |
| `DOCUSAURUS_BASE_URL` | `/docs/`                  | Docusaurus baseUrl                       |

Recommended `AION_*` overrides for the container context:

```bash
AION_REDIS_URL=redis://redis:6379/0          # service DNS Docker
AION_DATA_DIR=/app/data                       # mount aion_data
AION_FASTAPI_URL=http://backend:8001          # service-to-service
AION_PUBLIC_API_URL=https://${DOMAIN}/api
AION_CORS_ORIGINS=https://${DOMAIN}
# Do not use AION_CORS_ORIGINS=* in production without AION_CORS_ALLOW_WILDCARD=1
AION_LOG_LEVEL=INFO
AION_TURN_DIAGNOSTICS=0
AION_LLM_HEALTH_CACHE_SEC=45
```

| Variable | Default | Description |
|-----------|---------|-------------|
| `AION_CORS_ALLOW_WILDCARD` | off | `1` allows `AION_CORS_ORIGINS=*` even with `AION_ENV=prod` |
| `AION_LOG_LEVEL` | `INFO` | Root logger level (`setup_logging`) |
| `AION_LLM_HEALTH_CACHE_SEC` | `45` | Cache TTL for GET `/models` ping before each chat turn |

Quick setup:

```bash
./scripts/setup-aion-env.sh --docker   # copies .env.docker.example -> .env
vim .env                                # set DOMAIN, secrets, AION_API_URL
docker compose up -d --build
```

See [Deploy with Docker Compose](../deployment/docker.md) for the complete workflow
(path-based routing, troubleshooting, scalability).

---

## Multi-user MCP (HOME and credential store)

For enterprise environments where multiple users share the same backend, configure:

| Variable | Default | Description |
|-----------|---------|-------------|
| `AION_MCP_USER_HOME_ISOLATION` | `1` | `mcp_home` directory per user under `AION_DATA_DIR/users/...`. |
| `AION_MCP_USER_CREDENTIALS` | `0` | Enables encrypted credential store and `${AION_USER_*}` placeholders in the registry. |
| `AION_CREDENTIAL_ENCRYPTION_KEY` | (empty) | 32-byte hex key for AES-GCM; mandatory in prod if credentials=1. |
| `AION_DEFAULT_TENANT_ID` | `default` | Tenant for credential rows. |

Detailed guide: [MCP isolation per user](../mcp/user-isolation-and-credentials.md).

---

## Trade-off: Redis vs Local Fallback

AION V2 introduces Redis for multi-worker scalability.
- **With Redis**: Rate limiting and locks are shared across multiple worker instances. Ideal for production.
- **Local Fallback**: Uses in-memory dictionaries. Simple for local development, but does not scale across multiple processes.

## Unified DB vs Legacy
`AION_UNIFIED_DB=1` (default) enables the new unified schema that synchronizes Chat UI and API v1. If disabled, the system falls back to the old `chat_memory.db` and `chat.db` (strongly discouraged).

---

## Debugging configuration issues

### "Error 503 Unified DB disabled"
**Verify:** Check that `AION_UNIFIED_DB` is `1` and that the file `data/aion.db` exists or can be created. If you updated from a previous version, run `python scripts/migrate_to_aion_db.py`.

### "Files do not appear in S3"
**Verify:** Check `AION_STORAGE_BACKEND`. If set to `local`, files remain in the filesystem. Verify the `AION_STORAGE_S3_*` credentials if you use the `s3` backend.

---

## P1: Plan mode, prompt budget and centralized settings

| Variable | Default | Description |
|-----------|---------|-------------|
| `AION_PLAN_MODE_TOOL_FIRST` | `1` | Plan mode uses `draft_execution_plan` (tool) instead of `<plan>` tags. |
| `AION_PLAN_TEXT_PARSER` | `0` | Legacy text parser (only if tool-first off or rollback). |
| `AION_PLAN_FINALIZER_TIMEOUT_SEC` | `20` | Plan finalizer timeout (seconds). |
| `AION_PROMPT_LAYER_TOTAL_BUDGET` | `6000` | Estimated token budget for layers injected in the turn. |
| `AION_AGENT_EXEC_LEGACY_THREAD` | `0` | `1` = `Agent.run` in thread; `0` = `run_async` (default). |
| `AION_SETTINGS_LEGACY_FALLBACK` | `1` | Fallback `os.getenv` during migration to `src/settings.py`. |

`AION_API_URL` and `AION_MODEL` are **mandatory** (no hardcoded default IP). The limits per turn (`AION_TOOL_CALLS_MAX_PER_TURN`, `AION_STREAM_EVENTS_MAX_PER_TURN`, `AION_NO_PROGRESS_TIMEOUT_SEC`) are loaded from `TurnBudget` / `AionSettings`.

---

## Related documents

- [REST API v1](../api-and-runtime/rest-api.md)
- [SDK and Widget](../clients/sdk-and-widget.md)
- [Architecture](../architecture/overview.md)
- [Hermes features](../learning/hermes-features.md)

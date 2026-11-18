---
sidebar_position: 3
title: MCP user isolation and credentials
description: Per-process HOME/XDG isolation for MCP servers, encrypted per-user credentials, AION_USER placeholders, and the admin and chat flows.
---

# MCP user isolation and credentials

When many people share one AION installation, each person's connectors must use **their own** login and must not see anyone else's files or tokens. This page explains how AION keeps MCP (Model Context Protocol) server processes apart per user and how it stores connector credentials (passwords, API keys, OAuth tokens) encrypted, either shared by the organization or personal to each user. It is for administrators who set up connectors and for developers/operators who run the backend; end users only see the result in chat-ui under **My integrations**.

In a multi-user deployment, MCP processes must not share the system `$HOME` or global plain-text tokens. AION combines:

1. **HOME/XDG isolation** — each stdio worker gets dedicated directories under `data/users/<user_id>/mcp_home/` (variables `HOME`, `XDG_*`, `USERPROFILE`, `APPDATA`).
2. **Credential store** — the `user_mcp_credentials` table in `aion.db`, with encrypted values (AES-256-GCM), and resolution of `${AION_USER_*}` placeholders in the registry `env:` at spawn time.

## Environment variables

| Variable | Default | Role |
|----------|---------|------|
| `AION_MCP_USER_HOME_ISOLATION` | `1` | Enables per-user HOME/XDG directories for stdio MCP processes. |
| `AION_MCP_USER_CREDENTIALS` | `0` | Enables reading/writing per-user credentials and the `/v1/integrations` API. |
| `AION_CREDENTIAL_ENCRYPTION_KEY` | — | Hex key (32 bytes = 64 characters) for AES-GCM. Required in production if `AION_MCP_USER_CREDENTIALS=1`. |
| `AION_DEFAULT_TENANT_ID` | `default` | Tenant used for credential rows. |
| `AION_MCP_ENV_SCRUB` | `1` | Repository servers (`mcp_servers/`, `-m src.*`) inherit the backend env without the signing secrets (`AION_CHAT_AUTH_SECRET`, `AION_CHAT_UI_INTERNAL_SECRET`, `AION_ORCHESTRATION_INTERNAL_SECRET`, `AION_API_KEY_BOOTSTRAP`, `AION_SETUP_*`); third-party servers (`npx`, `node`, `mcp-remote`, external scripts) only get PATH/HOME/locale/proxy/certificates plus the registry `env:`. `0` = full env for everyone. |
| `AION_MCP_ENV_ALLOWLIST` | — | Extra variables (CSV) also passed to third-party servers. |

Generate the key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

:::danger Back up the encryption key
Losing `AION_CREDENTIAL_ENCRYPTION_KEY` makes the encrypted values unrecoverable. Keep the key in a company vault, together with the `aion.db` backups (see [Backup](#backup)).
:::

## Placeholders in the registry (`env:`) {#placeholder-nel-registry-env}

| Placeholder | Resolved from |
|-------------|---------------|
| `${VAR}` | `os.environ` / `.env` (historical behavior). |
| `${AION_USER_<UPPERCASE_SLUG>__<KEY>}` | The DB, for the current user. Example: `${AION_USER_EMAIL_MCP__ACCESS_TOKEN}` for the registry slug `email_mcp`. |
| `${AION_USER_<KEY>}` | Short form: the key is relative to the **slug of the server** whose `env` map contains it. |
| `${AION_USER_<UPPERCASE_SLUG>__*}` | Wildcard: a JSON object with **all** of the user's credentials for that slug (empty string if there are none). |

The wildcard is useful when key names depend on the admin configuration and cannot be listed in the registry, e.g. the credential sets of [`smb_files`](smb-files.md#server-multipli-e-set-di-credenziali). It never blocks the worker from starting, does not create form fields (the variable that receives it is just a carrier) and, in the Hub probe, receives a non-JSON mock value. Only connectors that declare it receive the bundle.

See also the example comment in `config_std/mcp_registry.yaml`.

## Credential modes (`credential_mode`)

The `credential_mode` field in the `mcp_server_configs` table defines how credentials are handled for each MCP server:

| Value | Meaning | Registry `env` | Credentials |
|-------|---------|----------------|-------------|
| **`none`** | No credentials needed. The server works without secrets or uses non-sensitive global variables. | `${VAR}` placeholders resolved from `os.environ` | No user form |
| **`org_shared`** | Credentials shared by the organization. The admin sets the values in the MCP Hub and they are injected via the backend `.env`. | `${VAR}` placeholders resolved from `os.environ` | "Managed by the organization" message in chat-ui |
| **`per_user`** | Each user sets their own personal credentials in chat-ui. Values are encrypted (AES-256-GCM) and isolated per `(user_id, tenant_id, server_slug, credential_key)`. | `${AION_USER_*}` placeholders resolved from the per-user credential store | Credential form in chat-ui → `/integrations` |

The mode is inferred automatically in `src/mcp_integration_sync.py` by looking at the placeholders in the registry environment variables:

- `${AION_USER_*}` → `per_user`
- `${VAR}` (standard variables) → `org_shared`
- No variables → `none`

## Write-only fields (`write_only`)

A `credential_fields` entry (in the connector catalog) can declare `write_only: true`, typically for passwords that must never be readable again, such as the Windows domain password of [`smb_files`](smb-files.md). For these fields:

- `GET /v1/integrations/credentials/{slug}/{key}` returns **403** `secret_write_only` (the check uses the DB schema and the catalog, so it cannot be bypassed with slug or key aliases): the value is read only by the runtime when it spawns the MCP process.
- The display hint is always `****`; hints saved earlier are masked in `GET /v1/integrations`.
- chat-ui hides the "eye" icon on an already saved field (it appears only while typing a new value, which replaces the saved one); admin-ui keeps the flag when saving the schema from the Hub.
- The flag is a catalog setting: fields without `write_only` keep the historical behavior.

## Unified Hub (admin) {#hub-unificato-admin}

Admin configuration happens in **one place only**: the **MCP Hub** (`/hub` → Edit configuration). See [MCP Hub install wizard](hub-wizard.md) for the full flow.

| `credential_mode` | Admin in the Hub | Registry `env` | Chat-ui |
|-------------------|------------------|----------------|---------|
| `none` | No secrets | Non-sensitive env only | No form |
| `org_shared` | Catalog credential form | Global `${VAR}` | "Managed by the organization" message |
| `per_user` | Field preview + "Apply suggested env" | `${AION_USER_*}` | User credential form |

The **credential schema** is detected automatically (README / `.env.example` / source code) in the wizard and the preview; the optional catalog `config/mcp_connector_catalog.yaml` only enriches curated integrations.

Additional APIs: `POST /admin/mcp-integrations/sync-from-registry`, `GET .../preview`, `POST .../advise`, `POST .../apply-suggested-env`.

Migrating existing installations:

```bash
alembic upgrade head
./.venv/bin/python scripts/sync_mcp_integration_from_catalog.py
```

Advisor profile: `mcp_integration_advisor` (chat-ui `?profile=mcp_integration_advisor&context=<slug>`).

## Data model

- **`mcp_server_configs`** — chat policy (`credential_mode`, `is_enabled_for_users`, schema from the catalog, `aion_connector_id`).
- **`user_mcp_credentials`** — one row per `(user_id, tenant_id, server_slug, credential_key)` with `value_encrypted`.

## API

- **Admin** (admin Bearer token): `GET/POST/PATCH/DELETE /admin/mcp-integrations` — manages the integration catalog.
- **Chat** (chat Bearer token, or BFF secret where applicable): `GET /v1/integrations`, `POST /v1/integrations/credentials`, `DELETE /v1/integrations/credentials/{slug}/{key}`.
  - Authentication: these endpoints do **not** accept API keys (`X-API-Key` gets `403 api_key_not_allowed`, see [API keys](../security/api-keys.md)); they use the same model as the other user-facing endpoints protected by `require_chat_auth`.
  - With `AION_CHAT_PASSWORD_AUTH=0` the list is anonymous and has no credential hints; **changes** (saving credentials) require a non-anonymous identity.

## UI

- **Admin UI** — **MCP Hub** (`/hub`): installation, registry env, user policy and credential mode. The "MCP policy (Hub)" entry focuses on integrations.
- **Chat UI** — "My integrations" (`/integrations`): form only for `credential_mode=per_user`; `org_shared` shows a message with no inputs.

## Operations

After the Alembic migrations, seed the catalog from the registry (idempotent):

```bash
./.venv/bin/python scripts/seed_mcp_integration_configs.py
```

`scripts/upgrade-aion.sh` / `upgrade_core.py` runs the seed in non-blocking mode after `init_unified_db`.

## OAuth

The OAuth 2.0 flow (Authorization Code + PKCE S256) is implemented in `src/api/v1/mcp_integrations.py`:

- `GET /v1/integrations/oauth/start` — starts the flow, with RFC 9728/8414 discovery and optional dynamic client registration (`AION_MCP_OAUTH_DYNAMIC_REGISTRATION`, default `1`).
- `GET /v1/integrations/oauth/callback` — browser callback that redirects to chat-ui (`<chat>/integrations`). The chat-ui base URL is resolved in this order: non-loopback `AION_CHAT_URL` / `AION_PUBLIC_CHAT_URL` → public `AION_OAUTH_REDIRECT_BASE_URL` / `AION_PUBLIC_API_URL` (without `/api`) → loopback `AION_PUBLIC_CHAT_URL` (dev) → proxy headers / `DOMAIN`.
- `POST /v1/integrations/oauth/callback` — programmatic code/token exchange.
- `GET /v1/integrations/{slug}/oauth-status` — the user's connection status.

Tokens (`OAUTH_TOKEN`, `OAUTH_REFRESH_TOKEN`) are stored encrypted in `user_mcp_credentials`. Automatic refresh happens in `src/runtime/credential_store.py` when the access token has expired but the refresh token is still valid. The HTTP exchange is centralized in `src/runtime/oauth_token_exchange.py`.

The server's OAuth `client_secret` (set by the admin or obtained through dynamic registration) is also encrypted at rest: `mcp_server_configs.oauth_config` contains only `client_secret_encrypted` (same `AION_CREDENTIAL_ENCRYPTION_KEY`, column type `EncryptedOAuthConfigJSON` in `src/data/encrypted_types.py`). Legacy plain-text values remain readable and are encrypted on the first write or by migration `x6y7z8a026`, which is skipped if the key is not set in the environment where it runs.

:::warning Architectural constraint
The PKCE state (`_oauth_pending`) lives in process memory, so the backend must run with `--workers 1`.
:::

## Backup

Losing `AION_CREDENTIAL_ENCRYPTION_KEY` makes the encrypted values unrecoverable: keep the key in a company vault together with the `aion.db` backups.

## End-to-end example: email (IMAP/SMTP)

Templates live in `config_std/`; the runtime reads `config/` (see `scripts/sync_config.py`).

1. **Registry** (`config/mcp_registry.local.yaml`): server `email-mcp-server` with `command: bun`, `args: [run, mcp_servers/email-mcp-server/index.ts]`, `aion_connector_id: email_imap`, env with `${AION_USER_EMAIL_MCP_SERVER__*}`.
2. **Profile** (`config/profiles/generic_assistant.yaml`): add `email-mcp-server` to `mcp_servers` and the `email_imap_mcp` skill.
3. **Hub**: AI wizard or Edit → `credential_mode=per_user` → Apply suggested env → enable in chat. Run the **probe** (`POST /admin/mcp/{slug}/probe`) to check `search_emails`, `send_email`, `list_folders`.
4. **Chat-ui**: My integrations → fill in `EMAIL_USER`, `EMAIL_PASSWORD`, `IMAP_*`, `SMTP_*`.
5. **Env**: `AION_MCP_USER_CREDENTIALS=1` and `AION_CREDENTIAL_ENCRYPTION_KEY` in the backend `.env`.

Migrating legacy keys (`IMAP_USER` → `EMAIL_USER`):

```bash
./.venv/bin/python scripts/migration/migrate_email_credential_keys.py --slug email-mcp-server --dry-run
```

## Unified architecture (pipeline)

A single function, `apply_integration_config` in `src/mcp_integration_sync.py`, is used by:

- Apply env (`POST /admin/mcp-integrations/{slug}/apply-suggested-env`)
- Marketplace post-install (`normalize_and_apply_env_after_install`)
- Integrity repair (`src/runtime/mcp_integration_integrity.py`)

Discovery and the registry define schema and env; the DB (`mcp_server_configs`) holds the policy; skills tell the agent **when** to use the tools (no prompt mapping in Python).

---
sidebar_position: 4
title: MCP Hub install wizard
description: Guided flow to install MCP servers from the marketplace, let the AI advisor analyze their requirements, choose org_shared or per_user credentials and roll out the policy.
---

# MCP Hub install wizard

The **MCP Hub** (`/hub` in the Admin UI) is where administrators manage the whole life cycle of MCP (Model Context Protocol) servers, the connectors that give the AION agent new tools. Its **install wizard** guides you from "I found a connector in the marketplace" to "users can use it in chat": it installs the server, works out which credentials it needs, lets you review the result and then rolls it out. This page is for administrators; the end of the page also explains what users see afterwards.

## Wizard overview

The wizard takes the administrator through **4 phases**:

```
┌──────────────┐    ┌──────────────────┐    ┌──────────────┐    ┌──────────────────┐
│ 1. Install   │ → │ 2. AI Analysis   │ → │ 3. Admin       │ → │ 4. Confirm &      │
│    (market)  │    │    (advisor)     │    │    Review      │    │    Distribute     │
└──────────────┘    └──────────────────┘    └──────────────┘    └──────────────────┘
```

## Phase 1: Select and install

Open **MCP Hub → Marketplace tab** and:

1. Search for an MCP server by name or keyword (e.g. "clickup", "email", "github").
2. Click **WIZARD** (guided install + AI analysis) or **INSTALL** (clone/registry only).
3. The system installs the server through `mcp_installer.py` (supports `npx`, `git clone`, binary download).
4. After installation the server appears in the MCP registry list (**Installed** tab).

Marketplace ids (`github:owner/repo`, `glama:owner/repo`, `npx:package`) are resolved **locally** at install time: the entry does not need to still appear in the search results. For GitHub repositories that are not indexed, use **Install from GitHub URL**, which analyzes the repository (`POST /admin/market/analyze-github`) and opens the wizard pre-filled.

**Endpoints involved:** `GET /admin/market/config` (configuration schema of a marketplace entry), `POST /admin/market/analyze-github` (GitHub repositories).

## Phase 2: Automatic AI analysis

As soon as installation is complete, the system automatically runs:

1. **Automatic discovery** ([`mcp_credential_discovery.py`](../../src/mcp_credential_discovery.py)): README, `.env.example`, source code, registry env.
2. **Optional catalog** (`config/mcp_connector_catalog.yaml`), only if a curated entry exists.
3. **Analysis of the environment variables** in the registry to infer the credential mode:
   - `${AION_USER_*}` placeholders → **`per_user`** (personal credentials for each user)
   - standard `${VAR}` placeholders → **`org_shared`** (credentials shared by the organization)
   - no sensitive variable → **`none`** (no credentials needed)
4. **Schema generation** from discovery (plus the optional catalog).
5. **Suggested env** (`suggested_env_per_user` / `suggested_env_org_shared`) with `${AION_USER_*}` placeholders.
6. **LLM advice** on the server's real files; if it proposes `none` but discovery found login env variables, it is corrected automatically.

**The AI advisor** (`POST /admin/mcp-integrations/advise`) produces a report with:

- `credential_mode` recommended (`none` | `org_shared` | `per_user`)
- `credential_schema`: list of required fields (key, label, type, required)
- `suggested_env`: map of variables to add to the registry
- `warnings`: any warnings
- `steps_markdown`: a plain-language checklist

The administrator can also start a **chat with the `mcp_integration_advisor` profile** for a deeper, interactive analysis.

## Phase 3: Admin review

The review screen shows the result of the AI analysis. The administrator can **change any of it**:

| Field | Description |
|-------|-------------|
| **Credential mode** | `none` / `org_shared` / `per_user` (dropdown) |
| **Credential schema** | For each field: key, label, type (text/password/oauth), required or not |
| **Available in chat** | Enables/disables the server for users (`is_enabled_for_users`) |
| **Users can disable** | If on, users see a toggle on their integrations page |
| **Apply suggested env** | Checkbox: if ticked, the variables are written to the registry on commit |

All fields are pre-filled with the AI suggestions and can be overridden. Before saving, the wizard can also start the server once with the current settings to list its tools (`POST /admin/market/probe-candidate`), so you can choose which tools to enable.

## Phase 4: Summary and rollout

The last screen shows a **summary** of every choice:

- Server slug and display name
- Selected credential mode
- Number of required credential fields
- Whether it is enabled for users
- Environment variables that will be written to the registry

Click **"Complete installation"** to confirm (`POST /admin/market/install-zero`). The system then:

1. **Updates the registry** (`mcp_registry.local.yaml`) with the environment variables (secrets are stored encrypted in `aion.db`).
2. **Creates or updates the policy** (`McpServerConfig` in `aion.db`) with mode, schema and enablement.
3. **Invalidates the agent cache**, so the new tools are available from the next chat turn.

## After rollout

### For administrators

- The server appears in **MCP Hub → Installed** with a badge showing its credential mode.
- You can change the policy at any time with **"Edit configuration"**.
- You can **disable** the server for all users or **delete** it completely.

### For users

- If `credential_mode = per_user`: the server appears in **chat-ui → My integrations** with a form for personal credentials.
- If `credential_mode = org_shared`: it appears with the message "Managed by the organization — no personal configuration required".
- **Availability for users** (Runtime tab of the dialog) combines `is_enabled_for_users` and `user_may_disable` into three states:

  | State | Settings | Effect |
  |-------|----------|--------|
  | **Hidden** | `is_enabled_for_users = false` | Not shown in *My integrations*; agents keep the tools |
  | **On, can be turned off** | `true` / `user_may_disable = true` | Visible, with a toggle on the card |
  | **Always on** | `true` / `user_may_disable = false` | Visible, no toggle (turning it off via the API returns 403) |

- A **yellow ⚠ icon** appears in the chat input area when some integrations are missing credentials.

### For agent profiles

- Add the server `slug` to the profiles that should use it (in `config/profiles/*.yaml`, field `mcp_servers`).
- The `mcp_integration_advisor` profile can help with configuration.

## Environment variables used by the wizard

The wizard relies on these backend variables:

```bash
# Enable the per-user credential store (required for per_user)
AION_MCP_USER_CREDENTIALS=1

# AES-256 encryption key (64 hex characters)
AION_CREDENTIAL_ENCRYPTION_KEY=<generated with secrets.token_hex(32)>

# HOME isolation for MCP processes
AION_MCP_USER_HOME_ISOLATION=1
```

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|--------------|-----|
| The server does not appear in chat-ui after installation | `is_enabled_for_users` is off | Turn the toggle on in MCP Hub |
| Credentials are not saved | `AION_MCP_USER_CREDENTIALS=0` | Set `AION_MCP_USER_CREDENTIALS=1` and restart the backend |
| "Integration not found" error in the wizard | Slug missing from the registry | Check that the marketplace installation completed |
| "Marketplace entry not found" with a `github:…` id | Backend version without local resolution of GitHub ids | Update the backend: `_find_marketplace_item` builds the payload from `github:owner/repo` without a new search; alternatively use **Install from GitHub URL** |
| Raw JSON error message in the wizard | FastAPI response not parsed by the UI | The Admin UI uses `readApiErrorMessage` on `detail`; update `admin-ui` if you still see `{"detail":…}` |
| The AI advisor proposes `none` but the server has env variables | The README only mentions config.toml | Discovery corrects this if it finds `MCP_EMAIL_*` or similar; check the install in `mcp_servers/<slug>` |
| Variables are saved but the MCP process gets old or empty values | Different values in the registry, the encrypted DB and the spawn env | `python scripts/mcp_env_inspect.py <slug>` (in Docker: `docker compose exec backend python scripts/mcp_env_inspect.py <slug>`) shows all three views; secrets appear as length + SHA-256 fingerprint |

### How `org_shared` variables are stored

- **Installation:** only the variables filled in the wizard are written to the registry. Empty fields are not written, so the MCP server uses its own default (previously they became a `${KEY}` placeholder resolved to an empty string).
- **Secrets** (names containing `key`, `token`, `secret`, `password`, `auth`, `pwd`): the value is stored encrypted in the DB (`user_mcp_credentials`, owner `default` and `org_shared`) and the registry keeps `${KEY}`. This applies both at installation and when the secret is changed via **Configure** → **Edit**: the field starts empty and, if left empty, the saved value does not change.
- **Applied immediately:** every save (Configure, policy, suggested env, reinstall) clears the agent cache and closes the pooled MCP workers of that server. The next chat turn restarts them with the new configuration, without restarting the backend.

## References

- **Admin UI page:** `admin-ui/app/hub/page.tsx` (with state and API calls in `admin-ui/components/hub/useHub.ts`)
- **Wizard component:** `admin-ui/components/DynamicWizardModal.tsx`
- **Backend wizard API:** `src/api/admin.py` → `/admin/market/config`, `/admin/market/analyze-github`, `/admin/market/probe-candidate`, `/admin/market/install-zero`
- **Sync logic:** `src/mcp_integration_sync.py` (mode and schema inference)
- **Discovery:** `src/mcp_credential_discovery.py` — **Optional catalog:** `config/mcp_connector_catalog.yaml`
- **Advisor profile:** `config_std/profiles/mcp_integration_advisor.yaml`

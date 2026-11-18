---
sidebar_position: 2
title: Connector catalog
description: The curated YAML catalog of recommended MCP connectors, its admin endpoint, how it feeds the MCP Hub, and integrity checks for company integrations.
---

# Connector catalog

AION connects to business systems (email, Google Workspace, Microsoft 365, GitHub, …) through **MCP (Model Context Protocol) servers**, managed from the registry and the marketplace in the Admin UI. The **connector catalog** is a curated list of recommended connectors with the extra details needed to install them safely: where the docs are, which environment variables they need, and how users log in. This page is for administrators who install connectors and for developers/operators who maintain the catalog.

You do not need a catalog entry to install a server: for any MCP server, AION detects the **credential schema** automatically from its README, `.env.example` and source code ([`src/mcp_credential_discovery.py`](../../src/mcp_credential_discovery.py)). The catalog only adds curated information on top.

## Catalog fields

The optional file **`config/mcp_connector_catalog.yaml`** lists curated integrations with:

- `id`, `title`, `description`, `category`;
- links to the vendor documentation (`official_doc_url`, `mcp_upstream_docs_url`);
- **`registry_search_hint`**: the search string used by the "Search marketplace" button on the **Admin → MCP Hub** page;
- **`example_registry_block`**: a commented snippet to copy into `config/mcp_registry.local.yaml` after you have audited the chosen package;
- **`required_env` / `optional_env`**: variable **names** only (never secrets in git), for stdio connectors;
- **`credential_fields`**: per-user fields (PAT, API key, …). Do **not** use `OAUTH_TOKEN` when `auth_type: oauth2` (the OAuth token is handled by the dedicated flow);
- **`runtime_env_aliases`** (optional): maps **env names expected by the MCP process** to **alternative keys** (e.g. snippets from Claude Code or other clients). When a stdio server starts, if the target key is empty and a source key has a value, the value is copied. Everything is declared in YAML, with no per-connector code.

## Local override

**`config/mcp_connector_catalog.yaml`** (same `version` + `connectors` structure) is optional: if it is missing from `config/`, the backend loads the committed template **`config_std/mcp_connector_catalog.yaml`**.

### Remote OAuth connectors

For a hosted MCP endpoint with OAuth login, a YAML declaration is enough:

```yaml
- id: my_service
  title: My Service          # UI label: "Sign in with My Service"
  install_type: remote
  remote_url: https://mcp.example.com/mcp
  auth_type: oauth2          # enables OAuth in chat-ui, hides PAT/OAUTH_TOKEN
  oauth_provider: my_service # optional; default = id
  featured_remote: true      # card in Admin → MCP Hub → Marketplace
  default_credential_mode: per_user
```

No code or per-service i18n strings are needed: `title` and `auth_type` drive both the API and chat-ui.

**Google Workspace MCP** (Gmail, Drive, Calendar, …), **GitHub Copilot MCP** and **Microsoft SharePoint / OneDrive** (Agent 365) require `client_credentials_required: true` in the `oauth:` block. The admin-ui then shows a warning, the redirect URI and links to `setup_doc_url` / `admin_setup_hint` from the catalog.

For SharePoint/OneDrive the Entra endpoints use `{tenant_id}` in the catalog; at runtime it is replaced with the GUID taken from the installed `remote_url` (`…/tenants/{guid}/servers/…`).

**Microsoft 365 (Softeria)** is a stdio connector separate from Agent 365: AION performs the Graph login and passes the token to the `npx` process. The Entra app registration, the `common` / `consumers` tenants and the presets are described in [microsoft-365.md](microsoft-365.md).

Other useful fields:

- `remote_url_template: true` — a URL with placeholders (e.g. `{tenant_id}`) to fill in before installing;
- `mcp_name_hints` — maps a registry name (`clickup-mcp-server`) to the catalog `id`.

The list of curated connectors lives in [`config_std/mcp_connector_catalog.yaml`](../../config_std/mcp_connector_catalog.yaml) (source of truth).

### Installing

| Action | How |
|--------|-----|
| Install a catalog connector | `POST /admin/mcp/install-from-catalog?connector_id=...` or the **Install** button in the Hub |
| Validate a remote URL before installing | `POST /admin/mcp/probe-remote` with `{ "url": "..." }` |
| Install a custom remote MCP server | `POST /admin/market/install-remote` (**Remote** dialog in the Hub) |

## API

| Method | Path | Role |
|--------|------|------|
| GET | `/admin/mcp/connector-catalog` | Catalog as JSON (admin Bearer token) |

Implementation: [`src/mcp_connector_catalog.py`](../../src/mcp_connector_catalog.py), route in [`src/api/admin.py`](../../src/api/admin.py).

## UI and DB policy

[`admin-ui/app/hub/page.tsx`](../../admin-ui/app/hub/page.tsx): **Recommended connectors**, marketplace installation and, in the *Edit configuration* dialog, the **User availability** section (`credential_mode`, schema from the catalog, suggested env).

Flow: catalog → registry (`aion_connector_id`) → sync to [`mcp_server_configs`](user-isolation-and-credentials.md#hub-unificato-admin) → chat-ui for `per_user`.

Script: `scripts/sync_mcp_integration_from_catalog.py` (does not change the registry `env` unless you pass `--apply-registry-env`).

## Integrity and uninstall

- **Uninstall** (`DELETE /admin/mcp/{slug}`): removes the registry entry, the DB policy, the marketplace artifacts and the **user credentials/preferences** linked to the slug.
- **Integrity check**: `GET /admin/mcp/integrity` reports orphaned credentials, stale policies, env not aligned with the schema, and credentials that can be migrated after a reinstall (same `aion_connector_id`).
- **Repair**: `POST /admin/mcp/integrity/repair-all`, or a single `POST /admin/mcp/integrity/repair` with `{ "issue": {...} }`.
- During registry sync, if the same `aion_connector_id` has credentials on an orphaned slug, they are migrated automatically to the new slug.
- The credential schema returned by the API includes `env_placeholder` and `suggested_env_yaml` for copy/paste into the registry YAML.

Implementation: [`src/runtime/mcp_integration_integrity.py`](../../src/runtime/mcp_integration_integrity.py).

## Session charts (same product epic)

Chart types (`chart_kind`) and the `AION_CHART_KIND_ENABLED` variable are documented in **[Session charts](../api-and-runtime/session-charts.md)**.

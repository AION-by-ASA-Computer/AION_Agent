---
title: MCP Integration Advisor
description: Admin guide for MCP policy, connector catalog, and registry env
---

# MCP Integration Advisor

## Useful admin APIs

- `GET /admin/mcp-integrations/{slug}/preview` — schema, inferred mode, suggested env, warnings.
- `POST /admin/mcp-integrations/advise` — body `{ "server_slug": "clickup", "admin_message": "..." }`.
- `POST /admin/mcp-integrations/sync-from-registry` — sync DB from registry + catalog.
- `POST /admin/mcp-integrations/{slug}/apply-suggested-env?credential_mode=per_user` — patch local env.

## Catalog

Discovery from README/sources of servers in `mcp_servers/`; optional catalog `config/mcp_connector_catalog.yaml`. Each curated connector may have:

- `credential_fields` — user/admin form
- `agent_guidance` — instructions for this MCP
- `integration_hints` — reuse tokens from n8n/Onyx

## ClickUp example (per_user)

```yaml
env:
  CLICKUP_API_KEY: "${AION_USER_CLICKUP__CLICKUP_API_KEY}"
```

Enable `is_enabled_for_users` and `credential_mode: per_user` in Hub → User availability.

## Gmail example (org_shared vs per_user)

Personal email → `per_user`. Org-wide shared mailbox → `org_shared` with `${GOOGLE_CLIENT_ID}` in .env.

## Security

- Do not write plaintext tokens in the registry when policy is `per_user`.
- Require `AION_MCP_USER_CREDENTIALS=1` and `AION_CREDENTIAL_ENCRYPTION_KEY` for multi-user production.

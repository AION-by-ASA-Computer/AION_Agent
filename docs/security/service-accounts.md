---
title: Service accounts
sidebar_position: 6
description: Non-human accounts managed by administrators for integrations that call AION with API keys, without login, SSO or personal data.
---

# Service accounts

A service account is a **non-human identity** for an integration (n8n, a nightly script, another backend). It uses AION only through [API keys](./api-keys.md). Unlike a personal key, which acts as a person, a service-account key has:

- its own identity (`svc-<slug>`);
- its own conversations;
- its own profile restrictions.

The integration keeps working when an employee leaves, and its traffic never shows up in anyone's chat-ui.

Only administrators create and manage service accounts and their keys, from **admin-ui → Service accounts** or `/admin/service-accounts`.

## Model

A service account is a regular `users` row with `account_type='service'`. Because conversations, profile access, memory, MCP credentials and SQL project membership are all keyed on `users.id` / `users.identifier`, every one of them works unchanged.

| Field | Meaning |
|---|---|
| `identifier` | `svc-<slug>`; slug `^[a-z0-9][a-z0-9._-]{1,60}$`. The `svc-` prefix is reserved: `POST /admin/users` rejects it with `422 identifier_reserved`. |
| `account_type` | `service` (people are `human`). |
| `disabled_at` | Set while the account is disabled. Keys are kept but rejected with `401 api_key_owner_disabled`. |
| `metadata.service` | `{description, ltm_enabled, created_by}`. |
| `max_api_keys` / `api_key_max_ttl_days` | Key quota (1–100) and maximum lifetime (1–**365** days). |

Migration `g5b6c7d035` adds `account_type` and `disabled_at`. On SQLite the startup schema patch adds them too.

## What a service account cannot do

| Path | Behaviour |
|---|---|
| Password login (`/auth/login`) | Always refused, even if a password hash were written by hand. |
| Chat token (`Bearer` from `/auth/login`) | `403 service_account_token_not_allowed`. |
| SSO login | An SSO identity is never linked to a service account. |
| Password links / temp passwords / forgot password / recover CLI | Refused (`409 service_account_no_password`) or skipped silently. |
| SSO migration | Always exempt; it does not count in the migration progress. |
| `/admin/*` | Refused: API keys never reach the admin router, so there is no `admin` scope. |
| `/v1/me/*` (API keys, memory, WhatsApp, Telegram, MCP integrations) | Refused: those endpoints need a chat token. |
| People endpoints (`PUT /admin/users/{id}`) | `409 service_account_use_dedicated_endpoint`. |

The available scopes are the user scopes (`chat`, `conversations:read|write`, `files:read|write`), with the same endpoint map as personal keys.

## Admin API (`/admin/service-accounts`)

Requires an admin chat token. Every mutating call writes `audit_log`:

- `service_account.create|update|disable|enable|delete`;
- `service_account.key.create|revoke`.

The payload never contains a secret (only key id, prefix, scopes and expiry).

| Endpoint | Purpose |
|---|---|
| `GET /admin/service-accounts` | `{items: [{id, identifier, display_name, description, disabled, disabled_at, ltm_enabled, max_api_keys, api_key_max_ttl_days, active_keys, last_used_at, created_at, created_by, profiles}]}` |
| `POST /admin/service-accounts` `{slug, display_name?, description?, ltm_enabled=false, max_api_keys=5, api_key_max_ttl_days=90}` | `201`. Errors: `422 invalid_service_slug`, `409 user_exists`. Allowed **in SSO mode too**. |
| `PATCH /admin/service-accounts/{id}` | Any of `display_name`, `description`, `disabled`, `ltm_enabled`, `max_api_keys`, `api_key_max_ttl_days`. |
| `DELETE /admin/service-accounts/{id}` | Deletes the account, its keys and profile access. Conversations are kept, as for people. |
| `GET /admin/service-accounts/{id}/keys` | `{policy, keys}` (same shape as `/v1/me/api-keys`). |
| `POST /admin/service-accounts/{id}/keys` `{name, scopes, expires_in_days}` | `201` with the key object plus `key`, **shown once**. Same errors as personal keys. |
| `DELETE /admin/service-accounts/{id}/keys/{key_id}` | Soft revoke. |

Profile restrictions use the existing `GET/POST /admin/users/{id}/profiles` with the service account's id.

`GET /admin/users` hides service accounts. Pickers that must offer them pass `?include_service=1`, and each row then carries `account_type`.

## Long-term memory

LTM is **off by default** for service accounts: automation traffic would otherwise flood the memory with low-value notes. While it is off, both extraction (`extract_and_persist`, pre-compaction flush included) and retrieval (`wake_up`) are skipped.

Enable it per account with `PATCH {"ltm_enabled": true}`. The flag is cached for about 30 seconds per process and the PATCH invalidates the cache. People are never affected, and the global `AION_LTM_*` switches still apply on top.

## Usage

```bash
# Admin: create the account and a 30-day chat key
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"slug":"n8n-reports","description":"Weekly KPI report"}' \
  https://aion.example.com/api/admin/service-accounts
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"n8n prod","scopes":["chat"],"expires_in_days":30}' \
  https://aion.example.com/api/admin/service-accounts/$ID/keys

# Integration: call the agent as svc-n8n-reports
curl -H "X-Api-Key: $AION_KEY" -H 'Content-Type: application/json' \
  -d '{"message":"Summarise last week KPIs"}' https://aion.example.com/api/v1/chat
```

The OpenAI-compatible `POST /v1/chat/completions` accepts the same key.

### Key rotation

Keys always expire, after at most `api_key_max_ttl_days` (365 at most). To rotate a key:

1. Create the new key while the old one is still valid; the quota must leave room for both.
2. Deploy the new key to the integration.
3. Revoke the old key.

`last_used_at` on each key shows whether the old key is still in use.

## Verification

`src/test/test_service_accounts.py` covers:

- creation and key use as `svc-*`;
- validation, quota and TTL;
- disable, enable and revoke;
- login and chat-token lockout;
- `/admin/*` refusal for service keys;
- the `/admin/users` separation and creation in SSO mode;
- profile restrictions, deletion and LTM gating.

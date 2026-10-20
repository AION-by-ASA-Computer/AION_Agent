---
sidebar_position: 1
title: Identity and chat auth
description: user_id resolution, chat-ui login, admin roles, database schema, and sub-agent status.
---

# Identity, users, and chat authentication

Operational guide for linking **real users** (tenant / organization), **agent profiles**, and **USER preferences** (SOUL/MEMORY deprecated — see [soul-memory-user](../configuration/soul-memory-user.md)), with authenticated chat-ui and conversation tracking.

:::info Env naming
Chat login uses `AION_CHAT_*` variables (`AION_CHAT_PASSWORD_AUTH`, `AION_CHAT_AUTH_SECRET`, `AION_SETUP_CHAT_IDENTIFIER`, `AION_SETUP_CHAT_PASSWORD`).
:::

:::tip Admin panel — always protected
Regardless of `AION_CHAT_PASSWORD_AUTH`, `/admin` is **always protected** via `require_admin_role`. See [`admin-ui.md`](../clients/admin-ui.md#admin-auth-always-on).
:::

## Current behavior

- **API** `POST /chat`: `user_id` in body and/or `X-AION-User-Id` (sanitized in `src/identity.py`), propagated to agent, MCP, and profile memory.
- **USER.md**: via `src/memory/memory_files.py` and `/admin/profile-memory/*` (SOUL/MEMORY deprecated — see [soul-memory-user](../configuration/soul-memory-user.md)).
- **chat-ui** (primary client): `POST /auth/login` → HMAC token signed with `AION_CHAT_AUTH_SECRET` (`src/chat_auth.py`, `src/api/auth_login.py`).
- **Persistence**: unified schema in `AION_DB_URL` (`conversations`, `messages`, `steps`, …). No separate chat database.

## Chat password login

1. Set `AION_CHAT_AUTH_SECRET` (e.g. `openssl rand -hex 32`).
2. Set `AION_CHAT_PASSWORD_AUTH=1` to require login on chat-ui.
3. Create users in the `users` table:
   - Setup wizard: `scripts/setup-aion-env.sh` (prompts to bootstrap the initial user during setup).
   - Admin UI or `POST /admin/users`
   - Password hash: `python -m src.chat_auth hash`
4. `identifier` + `AION_DEFAULT_TENANT_ID` scope login; the same identifier is used as `user_id` toward `USER.md` and `/chat`.

Non-interactive setup (`-y`): set `AION_SETUP_CHAT_IDENTIFIER` and `AION_SETUP_CHAT_PASSWORD` in `.env`, or provision via admin API.

With login disabled (`AION_CHAT_PASSWORD_AUTH=0`), chat endpoints remain open (dev only).

## Identity and `user_id` Resolution Hierarchy

During chat session initiation (e.g. `POST /chat/stream`), `user_id` is resolved dynamically based on the current client identity context using `_resolve_chat_user_id()`:

1. **Authenticated Chat Session**: If `AION_CHAT_PASSWORD_AUTH` is enabled and a valid Bearer token is provided via the `Authorization` header or query parameters (common in EventSource/SSE), the user identifier from the token payload takes absolute precedence.
2. **Open mode or trusted BFF**: only when the caller is anonymous (`AION_CHAT_PASSWORD_AUTH=0`) or presents `X-AION-Chat-Ui-Secret` (server-to-server), the user comes from:
   - The `user_id` provided inside the JSON request body.
   - The `X-AION-User-Id` request header (sanitized in `src/identity.py`).
3. **API key**: the key is its own principal, `apikey_<id>`. Header and body identities are ignored, so a key cannot act as a user.
4. **Default Value**: In open mode, if no identification mechanism is provided, the session owner defaults to `"default"`.

The resolution lives in `effective_user_id()` (`src/api/ownership.py`). With a chat token, `X-AION-User-Id` is ignored.

## Conversation Ownership

No one, admins included, can read another user's chats. Every endpoint that touches a conversation, session, step, file, chart, tool ledger, cron target or A2A session calls `assert_conversation_access()`; a mismatch returns **404**. Admin endpoints follow the same rule: `/admin/ltm/*` and `/admin/memory/facts` only serve the caller's own `user` scope, and `/admin/diagnostics/file` only serves files from smoke-test sessions (`smoke*`).

All resolved user IDs are sanitized through `sanitize_user_id()` to guarantee safe directory-friendly pathnames under `data/sessions/` and database entries.

## Admin Role Protection

Administrative endpoints `/admin/*` are gated via the `require_admin_role` FastAPI dependency.
- **Default (Grafana-style protection)**: `AION_ADMIN_PASSWORD_AUTH=1` requires an authenticated session token with the `admin` role. The server-to-server secret (`X-AION-Chat-Ui-Secret`) does **not** grant the admin role.
- **Development Bypass**: Setting `AION_ADMIN_PASSWORD_AUTH=0` allows administrative access without authentication checks (for local debugging/testing only).

## Principles

| Concept | Role |
|---------|------|
| **Identity** | Human user (email, OIDC subject, corporate username). |
| **`user_id` AION** | Stable string from identity (`sanitize_user_id`), used for `USER.md` and API headers. |
| **`session_id`** | Conversation / sandbox workspace; separate from identity. |
| **Agent profile** | User-selected profile mapped to `profile` in `/chat`. |



## Roadmap (enterprise)

- User catalog CRUD and role-based profile ACL.
- OAuth / SSO for chat-ui (replace or complement password auth).
- Multi-tenant filesystem prefixes under `data/sessions/` where needed.

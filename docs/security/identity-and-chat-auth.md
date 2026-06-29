---
sidebar_position: 1
title: Identity and chat auth
description: user_id resolution, chat-ui login, admin roles, database schema, and sub-agent status.
---

# Identity, users, and chat authentication

Operational guide for linking **real users** (tenant / organization), **agent profiles**, and **USER preferences** (SOUL/MEMORY deprecated — see [soul-memory-user](../configuration/soul-memory-user.md)), with authenticated chat-ui and conversation tracking.

:::info Env naming
Chat login uses `AION_CHAT_*` variables. Legacy `AION_CHAINLIT_*` / `CHAINLIT_AUTH_SECRET` names are still read as fallback; `scripts/upgrade-aion.sh` migrates them in `.env`.

| Current name                 | Legacy alias (fallback only)      |
|------------------------------|-----------------------------------|
| `AION_CHAT_PASSWORD_AUTH`    | `AION_CHAINLIT_PASSWORD_AUTH`     |
| `AION_CHAT_AUTH_SECRET`      | `CHAINLIT_AUTH_SECRET`            |
| `AION_SETUP_CHAT_IDENTIFIER` | `AION_SETUP_CHAINLIT_IDENTIFIER`  |
| `AION_SETUP_CHAT_PASSWORD`   | `AION_SETUP_CHAINLIT_PASSWORD`    |
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
2. **Anonymous or Non-Chat Client (Bypass/Fallback)**: If no chat token is resolved, it falls back to:
   - The `user_id` provided inside the JSON request body.
   - The `X-AION-User-Id` request header (sanitized in `src/identity.py`).
   - The programmatic client identifier associated with the presented `X-Api-Key` or API key Bearer token.
3. **Default Value**: If no identification mechanism is provided, the system defaults the session owner to `"default"`.

All resolved user IDs are sanitized through `sanitize_user_id()` to guarantee safe directory-friendly pathnames under `data/sessions/` and database entries.

## Admin Role Protection

Administrative endpoints `/admin/*` are gated via the `require_admin_role` FastAPI dependency.
- **Default (Grafana-style protection)**: `AION_ADMIN_PASSWORD_AUTH=1` requires a authenticated session token with the `admin` role, or an authorized server-to-server secret (`X-AION-Chat-Ui-Secret` matching `AION_CHAT_UI_INTERNAL_SECRET`), or a programmatic API key with admin scope.
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

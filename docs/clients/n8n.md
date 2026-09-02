---
title: N8N Integration
sidebar_position: 4
description: Connect AION Agent to n8n workflows via the community node and sync chat API.
---

# N8N Integration

AION can drive **n8n** automations through a community node that selects an existing
agent **profile** and runs a synchronous chat turn.

The community package lives in a **separate repository**: `n8n-nodes-aion`
(sibling of this monorepo). Keep packaging, npm publish, and n8n CLI tooling there;
this document describes the AION-side contract and how to wire credentials.

## Architecture

```text
n8n workflow
  └─ AION Agent node (credentials: Base URL + API key)
       ├─ GET  /profiles          → profile dropdown
       ├─ POST /v1/chat           → Ask (sync JSON)
       └─ POST /v1/conversations  → Create conversation (optional multi-turn)
```

Prefer **`POST /v1/chat`** over SSE (`/v1/chat/stream`). n8n HTTP nodes do not
consume Server-Sent Events cleanly; the sync endpoint drains the agent pipeline
until a `final` result (or timeout).

## Prerequisites (AION)

1. AION API reachable from the n8n host (same Docker network, or public URL via Caddy).
2. An **API key** from Admin → API Keys:
   - Ask: chat access (key accepted by `require_chat_auth`)
   - Create conversation: also `conversations:write`
3. At least one profile under `config/profiles` (e.g. `aion_std`).

### Base URL tips

| Deploy | Base URL example |
|--------|------------------|
| Local uvicorn | `http://localhost:8001` |
| Docker Compose + Caddy | `https://cliente.example.com/api` |
| Dev compose (backend only) | `http://localhost:8001` |

Do **not** add a trailing slash.

## Sync chat API

`POST /v1/chat` (Requires Chat Auth / API key)

**Request:**

```json
{
  "message": "Summarize yesterday's incidents",
  "profile": "aion_std",
  "conversation_id": null,
  "user_id": "n8n",
  "message_source": "internal_trigger",
  "timeout_seconds": 300
}
```

| Field | Notes |
|-------|--------|
| `message` | Required |
| `profile` / `profile_slug` / `profile_name` | Default `aion_std` |
| `conversation_id` / `session_id` | Omit to auto-create |
| `message_source` | Default `internal_trigger` for automation |
| `timeout_seconds` | Default `300`, max `3600`; returns **504** on timeout |

**Response:**

```json
{
  "text": "…",
  "conversation_id": "uuid",
  "session_id": "uuid",
  "profile": "aion_std",
  "success": true,
  "charts": []
}
```

### Profiles for the dropdown

`GET /profiles` (Requires Chat Auth) — returns the profiles allowed for the
caller (same list used by chat-ui).

## Install the community node

See the package README in `n8n-nodes-aion` for npm / local / Docker install.

Quick local link:

```bash
cd /path/to/n8n-nodes-aion
pnpm install && pnpm build
# then N8N_CUSTOM_EXTENSIONS=/path/to/n8n-nodes-aion  (or npm link into ~/.n8n/custom)
```

## Example workflow

1. Create credentials **AION API** (Base URL + key).
2. Add node **AION Agent** → Resource **Agent** → Operation **Ask**.
3. Pick a **Profile** from the dropdown.
4. Set **Message** (expression OK, e.g. `{{ $json.body }}`).
5. Use `{{ $json.text }}` downstream (Slack, email, HTTP, …).

Multi-turn: **Conversation → Create**, then Ask with
`conversationId = {{ $json.id }}`.

## Security notes

- Do not use unauthenticated `POST /a2a/invoke` from n8n in production.
- Prefer a dedicated API key with least privilege for automation.
- Use a stable `user_id` (default `n8n`) if you want isolated LTM/STM for bots;
  use a real user id when the workflow acts on behalf of a person.

## Related

- [REST API](../api-and-runtime/rest-api.md) — full chat/stream reference
- [SDK and Web Widget](./sdk-and-widget.md) — other external clients
- [Profiles](../configuration/profiles.md) — authoring agent profiles

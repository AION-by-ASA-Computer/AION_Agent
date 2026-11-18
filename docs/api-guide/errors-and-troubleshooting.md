---
sidebar_position: 7
title: Errors and troubleshooting
description: What each HTTP status and error code returned by the AION API means and how to fix it.
---

# Errors and troubleshooting

When a call fails, AION answers with an HTTP status code and, in most cases, a JSON body `{"detail": "<code or message>"}`. This page lists the errors you are likely to meet while integrating, what they mean and what to do. It is for developers and IT staff debugging an integration.

## Authentication and permissions

| Status | `detail` | Meaning | What to do |
|---|---|---|---|
| 401 | `api_key_invalid_format` | The key is malformed. | Send the full key `aion_<8>_<32>`, without quotes or spaces. |
| 401 | `api_key_invalid` | No such key. | Check you copied the right key, for the right AION installation. |
| 401 | `api_key_revoked` | The key was revoked. | Create a new key. |
| 401 | `api_key_expired` | The key expired. | Create a new key; plan rotation before expiry. |
| 401 | `api_key_owner_disabled` | The owner's account or their API-key permission is disabled. | Ask the administrator. |
| 401 | other | No credentials, or an expired login token. | Send `Authorization: Bearer <key>` or `X-Api-Key: <key>`. |
| 403 | `api_key_not_allowed` | This endpoint never accepts API keys (admin API, memory, credentials, settings, key management…). | Use the chat app or admin panel for that task. |
| 403 | `missing_scope` | The key lacks the permission this endpoint needs. | Create a key with the right [permission](./get-an-api-key.md#which-permissions-do-i-need). |
| 403 | `profile_not_allowed` / `model_not_allowed` | The owner may not use that profile. | Pick a profile from `GET /profiles` or ask the administrator. |
| 403 | `password_change_required` | The owner has a temporary password. | The user must sign in to the chat app and change it. |

## Requests and resources

| Status | Meaning | What to do |
|---|---|---|
| 400 | Invalid input, e.g. a conversation id with forbidden characters. | Ids: letters, digits, `-`, `_`, 4–128 characters. |
| 404 | Conversation, file or model not found — **or it belongs to someone else** (AION does not reveal other people's conversations). | Check the id and that you are using the owner's key. |
| 404 `model_not_found` | Unknown profile slug on the OpenAI-compatible API. | Use an `id` from `GET /v1/models`. |
| 422 | The JSON body does not match the schema (missing `message`, wrong type…). | The response lists the invalid fields. |

## Limits and server problems

| Status | Meaning | What to do |
|---|---|---|
| 429 | Too many requests. Headers `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` tell you the limits. | Slow down and retry after the reset time. |
| 504 | The turn took longer than the allowed time (`timeout_seconds` on `/v1/chat`, `AION_OPENAI_COMPAT_TIMEOUT_SEC` on the OpenAI API). | Raise `timeout_seconds` (up to 3600), use streaming, or split the task. The work may still be saved in the conversation. |
| 503 | A required service (database, Redis, session storage) is unavailable. | Ask the administrator to check the server health. |

## Errors inside a streamed answer

On `POST /v1/chat/stream` the HTTP status is `200` once the stream starts; later problems arrive as events:

- `{"type": "error", "content": "…"}` — the turn failed or was interrupted (cancellation, limits, model unreachable).
- `{"type": "llm_error", "code": "…", "message": "…"}` — the AI model returned an error (for example wrong credentials or quota exceeded on the provider side): tell the administrator.
- an `event: error` frame with `{"error": "…", "code": "…"}` — failure before the agent started, e.g. `profile_not_found`.

The end-of-turn rules are in [Chat stream events](../api-and-runtime/sse-events.md#rules-for-clients).

## Common problems

**The call hangs for minutes.** It is probably working: the agent may be using many tools. Use streaming to see progress, and set client and proxy timeouts to at least 5–10 minutes.

**The answer ignores the file I uploaded.** With `/v1/chat` you cannot pass attachments; use `/v1/chat/stream` with `attachments` (see [Conversations and files](./conversations-and-files.md#ask-the-agent-about-a-file)).

**The agent doesn't remember the previous message.** You did not send the `conversation_id` of the first call, so every call started a new conversation.

**I see the conversations in the chat sidebar.** That is expected: the key acts as you. Use a [service account](../security/service-accounts.md) for integrations whose conversations should not appear in a person's sidebar.

**Open the conversation in the chat app** to see exactly what the agent did (tools, inputs, outputs): it is the fastest way to debug an unexpected answer.

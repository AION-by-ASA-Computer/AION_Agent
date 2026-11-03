---
sidebar_position: 5
title: Chat stream events (SSE)
description: Wire format, event types, ordering and end-of-turn rules of POST /v1/chat/stream and its reconnect endpoint.
---

# Chat stream events (SSE)

`POST /v1/chat/stream` and `GET /v1/chat/stream/reconnect/{conversation_id}`
(scope `chat`) return a `text/event-stream`. This page is the reference for
clients that consume it directly, such as AION SRE. Both routes are part of the
[API contract](./rest-api.md#api-contract-and-deprecation).

The event models live in `src/api/v1/sse_schema.py` (`ChatStreamEvent`) and are
published in OpenAPI as the `200` response of both routes (`Sse*` schemas).
`src/test/test_sse_contract.py` validates a live turn against them, and
`src/test/fixtures/sse/chat_stream_basic.txt` is a recorded example.

## Wire format

| Frame | Content |
| --- | --- |
| `event: message` + `data: {...}` | One JSON event with a `type` field (tables below). |
| `event: error` + `data: {...}` | Failure outside the agent pipeline: `{"error": str, "code"?: str, "available_slugs"?: [str]}`, no `type`. The stream closes right after. |
| `: aion-open` | First line of every stream that is attached to a turn. |
| `: aion-not-active` | Only line of a reconnect when no turn is running. |
| `: ping ...` | Keep-alive comment, every 15 seconds. |

There is no `id:` or `retry:` field: events cannot be resumed with
`Last-Event-ID`.

Example (abridged from the recorded fixture):

```text
: aion-open

event: message
data: {"type": "turn_started", "user_message_id": "…", "assistant_message_id": "…"}

event: message
data: {"type": "tool_event", "event": {"type": "tool_start", "id": "call-1", "name": "splunk_search", "input": {"q": "error"}}}

event: message
data: {"type": "tool_event", "event": {"type": "tool_end", "id": "call-1", "name": "splunk_search", "output": "3 results", "input": {"q": "error"}, "tokens_in": 6, "tokens_out": 3}}

event: message
data: {"type": "token", "content": "Found "}

event: message
data: {"type": "stream_end", "finish_reason": "stop"}

event: message
data: {"type": "final", "text": "Found 3 errors."}
```

## Rules for clients

- **Ignore unknown `type` values and unknown fields.** New event types and new
  fields are compatible changes and can appear in any minor release.
- **The turn ends when the stream closes**, not when `final` arrives:
  - normal turn: `final` is the last event;
  - `error` followed by `final`: cancellation, timeout, turn guards (too many
    tool calls, no progress, output limits);
  - `error` without `final`: LLM not configured or unreachable, project access
    denied, account errors;
  - `event: error` frame: exception outside the pipeline (for example
    `code: "profile_not_found"`);
  - neither `error` nor `final`: the turn was stopped with
    `POST /v1/chat/stop` after the grace period, or the backend restarted.

  In every case, the saved outcome is in
  `GET /chat-ui/conversations/{conversation_id}/messages`.
- `turn_started` is always the first event and carries the ids under which the
  messages are saved.
- `stream_end` closes **one LLM call**. A turn with tools has several.

## Reconnect

`GET /v1/chat/stream/reconnect/{conversation_id}` replays **every event of the
turn in progress** from the start (the history is kept in the backend process
memory), then continues live. When the turn has already finished, or after a
backend restart, the response is a single `: aion-not-active` comment: read the
result from the messages endpoint. `GET /chat-ui/conversations/{id}/stream-status`
says whether a turn is running.

## Event types

### Turn

| `type` | Fields | Notes |
| --- | --- | --- |
| `turn_started` | `user_message_id`, `assistant_message_id` | Always first. |
| `token` | `content` | Chunk of the answer text. |
| `reasoning` | `reasoning` | Chunk of model reasoning, when the model exposes it. |
| `stream_end` | `finish_reason` | End of one LLM call (`stop`, `length`, `tool_calls`, ...). |
| `final` | `text` | Final answer of the turn. |
| `turn_status` | `phase`, `message`, `tool`? | Informational notice (guards, memory tools, truncated output). |
| `turn_outcome` | `code`, `message`, `details`? | Anomalous outcome (missing answer, interrupted turn). |
| `error` | `content` | Turn error; see the end-of-turn rules. |
| `llm_error` | `code`, `message`, `content`, `exc_type` | Classified LLM failure; `content` equals `message`. |
| `prompt_snapshot` | `assistant_message_id`, `snapshot` | Prompt sent to the LLM (debug panel of chat-ui). |
| `pii_messages_to_replace` | `replacements` | PII review: messages to rewrite. |

### Tools

`tool_event` wraps one event in `event`:

| `event.type` | Fields |
| --- | --- |
| `tool_start` | `id`, `name`, `input` |
| `tool_end` | `id`, `name`, `input`, `output`, `tokens_in`, `tokens_out` (a skipped tool has `result` and `error: true` instead) |
| `tool_error` | `id`, `name`, `input`, `error` |
| `orchestration_plan_pending` | same fields as the top-level event below |

### Artifacts

| `type` | Fields |
| --- | --- |
| `artifact_start` | `artifact`: `identifier`, `type`, `title`, `auto_execute` |
| `artifact_content` | `content`, `artifact_id` |
| `artifact_end` | `artifact`: `identifier`, `type`, `title`, `path`, `version`, `saved`, `storage_key`?, `execution`? |

### Plans

| `type` | Fields |
| --- | --- |
| `plan_phase` | `phase`, `plan_id`, `message`? |
| `plan_progress` | `plan_markdown`, `plan_id`, `revision`, `tasks_count`? |
| `plan_error` | `plan_id`, `message` |
| `orchestration_plan_pending` | `plan_id`, `plan`, `plan_markdown`, `todos`, `annotations`, `revision`, `goal` |

### Context window

| `type` | Fields |
| --- | --- |
| `context_budget` | `phase`, `total`, `max_prompt`, `trigger`, `message_count`, `pct`, `parts[]` (`key`, `tokens`, `pct`) |
| `context_compacting` | `active`, `tokens`, `trigger`, `phase`, `mid_turn`? |
| `context_recovery` | `attempt`, `message`, `tokens_before`, `tokens_after` |

### Never sent

`keepalive`, `done`, `llm_call`, `llm_tokens` and `request_sync` are internal
to the pipeline and never reach the stream.

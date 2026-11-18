---
sidebar_position: 3
title: PII review token
description: How the PII confirmation token travels from the browser to the SmartRoute gateway through the whole AION chain.
---

# PII review token: the full propagation chain

Some messages contain PII (personally identifiable information, such as names,
phone numbers or tax codes). When the privacy filter of the SmartRoute gateway
blocks such a message, the user can review it in chat-ui and confirm. On
confirmation, chat-ui generates a **confirmation token**
(`aion_pii_review_token`) that must reach the SmartRoute gateway to unblock the
request.

This page is for developers. It documents each step of the chain, the files
involved and the easy-to-miss pitfalls, plus a checklist for adding new
PII-like flags.

---

## The chain at a glance

```
Browser (chat-ui)
    │  opts.aion_pii_review_token
    ▼
ChatWorkspace.tsx  →  runChatRequest(message, { aion_pii_review_token })
    │  field in the JSON payload
    ▼
lib/api/aion.ts  →  postChatStream({ …, aion_pii_review_token })
    │  HTTP POST /v1/chat/stream
    ▼
src/api/v1/chat.py  →  ChatStreamBody.aion_pii_review_token
    │  added to metadata{}
    ▼
src/agent_pipeline.py  →  extra_body["aion_pii_review_token"]
    │  HTTP POST /v1/chat/completions (→ SmartRoute)
    ▼
SmartRoute: aion/gateway/routers/chat.py  →  ChatCompletionRequest.aion_pii_review_token
    │  passed to RoutingContext.pii_review_token
    ▼
Privacy filter / bypass logic ✓
```

:::warning The token is never forwarded automatically
Every hop must declare and pass the field explicitly. Pydantic models drop
fields they do not declare, so a missing declaration anywhere silently loses the
token. The [checklist](#checklist-when-you-add-a-new-pii-like-flag) below lists
every place to touch.
:::

---

## Step by step

### 1. Chat-UI — `ChatWorkspace.tsx`

The component calls `runChatRequest`, passing the token in the options:

```tsx
// components/chat/ChatWorkspace.tsx
void runChatRequest(finalPrompt, {
  aion_pii_review_token: piiToken,
});
```

`runChatRequest` accepts `opts.aion_pii_review_token` and includes it in the
payload of the `postChatStream` call:

```tsx
const stream = await postChatStream(
  {
    // …other fields…
    aion_privacy_filter_review_content: piiReviewEnabled,
    aion_pii_review_token: opts?.aion_pii_review_token,   // ← required
  },
  token,
  abortRef.current.signal
);
```

:::caution
If `aion_pii_review_token` is not passed in `opts` **and** explicitly added to
the `postChatStream` payload, the field never reaches the backend (Pydantic
discards undeclared fields).
:::

### 1.1 Rewriting the original message in place

When the token is sent with the confirm action (`confirm`), the frontend **does
not create a new user message**. Instead, it replaces the text of the original
message with the redacted text, so the chat does not show duplicates.
Two mechanisms make this work:

1. **Frontend state**: `handlePiiAction` finds the original `user_message_id`
   (the user message that precedes the assistant turn). This ID is passed as
   `userMessageIdOverride` to `runChatRequest`, which updates the existing user
   bubble in place.
2. **Backend storage**: the backend receives the new request (`postChatStream`)
   with the same `user_message_id`. The API (`POST /chat-ui/conversations/{conv_id}/messages`
   via `saveChatMessage`, and later during pipeline processing) performs an
   **upsert** of the content in the DB, permanently overwriting the original,
   unredacted message.

### 2. TypeScript type — `lib/api/aion.ts`

The `ChatStreamRequest` type must declare the field:

```ts
// lib/api/aion.ts
export type ChatStreamRequest = {
  // …
  aion_privacy_filter_review_content?: boolean;
  aion_pii_review_token?: string;   // ← must be present
};
```

### 3. FastAPI backend — `src/api/v1/chat.py`

The Pydantic model `ChatStreamBody` must declare the field; without an explicit
declaration the parser silently drops the value:

```python
# src/api/v1/chat.py
class ChatStreamBody(BaseModel):
    # …
    aion_privacy_filter_review_content: Optional[bool] = Field(default=None)
    aion_pii_review_token: Optional[str] = Field(default=None)   # ← required
```

The value is then injected into the `metadata` dict passed to the pipeline:

```python
metadata={
    **(body.metadata or {}),
    **({"aion_privacy_filter_review_content": body.aion_privacy_filter_review_content}
       if body.aion_privacy_filter_review_content is not None else {}),
    **({"aion_pii_review_token": body.aion_pii_review_token}
       if getattr(body, "aion_pii_review_token", None) is not None else {}),
},
```

### 4. Agent pipeline — `src/agent_pipeline.py`

Before every call to the LLM, the pipeline builds the `extra_body` attached to
the request sent to SmartRoute. **Both** PII flags must be copied from
`metadata` into `extra_body`:

```python
# src/agent_pipeline.py  ~L1840
if metadata and metadata.get("aion_privacy_filter_review_content") is not None:
    eb = dict(gen_kw.get("extra_body") or {})
    eb["aion_privacy_filter_review_content"] = metadata["aion_privacy_filter_review_content"]
    gen_kw["extra_body"] = eb

if metadata and metadata.get("aion_pii_review_token") is not None:
    eb = dict(gen_kw.get("extra_body") or {})
    eb["aion_pii_review_token"] = metadata["aion_pii_review_token"]
    gen_kw["extra_body"] = eb
```

:::warning
These two blocks are **separate and independent**: if you add a new PII field
in the future, remember to add its block here too. The token is never copied
automatically — the step must be explicit.
:::

### 5. SmartRoute gateway — `aion/gateway/routers/chat.py`

`ChatCompletionRequest` (with `model_config = ConfigDict(extra="allow")`)
receives the token in `extra_body` and exposes it as a declared attribute:

```python
class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    # …
    aion_privacy_filter_review_content: bool | None = None
    aion_pii_review_token: str | None = None   # ← must be declared
```

It is then passed to the `RoutingContext`:

```python
ctx = RoutingContext(
    # …
    privacy_filter_review_content=body.aion_privacy_filter_review_content,
    pii_review_token=body.aion_pii_review_token,
)
```

---

## Checklist: when you add a new PII-like flag

Follow these 6 steps in order:

1. **`ChatStreamRequest`** in `chat-ui/lib/api/aion.ts` — add the field to the TS type
2. **`runChatRequest` opts** in `ChatWorkspace.tsx` — add the field to the `opts` type
3. **`postChatStream` payload** in `ChatWorkspace.tsx` — include the field in the body
4. **`ChatStreamBody`** in `src/api/v1/chat.py` — declare the Pydantic field
5. **`extra_body` merge** in `src/agent_pipeline.py` — copy the field from `metadata` into `gen_kw["extra_body"]`
6. **`ChatCompletionRequest`** in SmartRoute — declare the field in the gateway model

---

## Quick debugging

| Symptom | Most likely cause |
|---------|-------------------|
| Field is `None` in the AION backend log | Not declared in `ChatStreamBody` (step 4) |
| Field missing from the gateway log | Not copied into `extra_body` in `agent_pipeline.py` (step 5) |
| Field present in the gateway log but not in `RoutingContext` | Not declared in `ChatCompletionRequest` in the gateway (step 6) |
| TypeScript field is `undefined` | Missing from the `ChatStreamRequest` type declaration (step 1) |

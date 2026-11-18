---
sidebar_position: 6
title: OpenAI-compatible API
description: Use AION from the OpenAI SDKs and from tools like Open WebUI, LibreChat or Continue - each AION profile appears as a model.
---

# OpenAI-compatible API

Many tools and libraries already know how to talk to the OpenAI Chat Completions API. AION offers the same interface, so you can plug it in by changing only the **base URL** and the **API key**. Each AION **profile appears as a model**: choosing the "model" `aion_std` means talking to the standard AION agent, with its tools and memory. This page is for developers integrating existing software.

## Settings

| Setting | Value |
|---|---|
| Base URL | `<AION base URL>/v1` — for example `https://aion.example.com/api/v1` (Docker) or `http://localhost:8001/v1` (developer setup) |
| API key | An AION key with the **Chat** permission (`aion_…`) |
| Model | A profile slug, for example `aion_std`. List them with `GET /v1/models`. |

## Python (official OpenAI SDK)

```python
import os
from openai import OpenAI  # pip install openai

client = OpenAI(base_url=f"{os.environ['AION_URL']}/v1", api_key=os.environ["AION_API_KEY"], timeout=600)

for m in client.models.list():
    print(m.id)  # the profiles you can use

resp = client.chat.completions.create(
    model="aion_std",
    messages=[{"role": "user", "content": "Write a short welcome email for a new colleague."}],
)
print(resp.choices[0].message.content)
```

Streaming works as usual:

```python
stream = client.chat.completions.create(model="aion_std", stream=True,
    messages=[{"role": "user", "content": "Explain RAID 5 in three sentences."}])
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## JavaScript (official OpenAI SDK)

```js
import OpenAI from "openai"; // npm install openai

const client = new OpenAI({ baseURL: `${process.env.AION_URL}/v1`, apiKey: process.env.AION_API_KEY });
const resp = await client.chat.completions.create({
  model: "aion_std",
  messages: [{ role: "user", content: "Write a short welcome email for a new colleague." }],
});
console.log(resp.choices[0].message.content);
```

## Chat front-ends (Open WebUI, LibreChat, Continue…)

Add an "OpenAI-compatible" connection with the base URL and key above. The model list is loaded from `GET /v1/models`, so users see the AION profiles they are allowed to use.

## How it differs from OpenAI

| Topic | Behaviour in AION |
|---|---|
| **Tools** | The profile's tools run **inside AION**. A `tools` array in the request is ignored and you never receive `tool_calls`: you only get the final text. In streaming, tool activity is sent as SSE comments (`: aion-tool`) that SDKs ignore. |
| **Conversation memory** | Clients normally resend the whole chat each time. AION keeps one session per conversation so files and tool results survive between calls. Send `X-AION-Conversation-Id` (header) or `metadata.aion_conversation_id` to choose the session explicitly; otherwise it is derived from the user, the model and the **first** user message — two new chats starting with the same sentence would share a session. The id is returned in the `X-AION-Conversation-Id` response header and in `aion_conversation_id`. |
| **Sampling parameters** | `temperature`, `max_tokens` and similar fields are ignored: limits are set by the administrator. `n` must be 1. |
| **Thinking** | Always off on this endpoint, for fast answers. Reasoning, when a profile produces it, is in `delta.reasoning_content`. |
| **Images and other content parts** | Only text parts of a message are used. |
| **LLM selection** | `model` can be `profile@provider_slug` (or header `X-AION-Llm-Provider`) to pick one of the configured LLM providers for the turn. |
| **Timeout** | A turn can last up to `AION_OPENAI_COMPAT_TIMEOUT_SEC` (default 300 s); then `504`. |

Errors: unknown model → `404 model_not_found`; profile not allowed for the key's owner → `403 model_not_allowed`.

Full details: [REST API reference → OpenAI-compatible facade](../api-and-runtime/rest-api.md#openai-compatible-facade).

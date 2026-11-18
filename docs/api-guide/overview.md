---
sidebar_position: 1
title: API overview
description: What you can do with the AION REST API, the base URL, how to authenticate and which endpoint to choose.
---

# API overview

The AION REST API lets any program talk to the agent: a Python script, a backend service, an n8n workflow, a chatbot already built with the OpenAI SDK. It is the same agent people use in the chat, with the same profiles, tools and memory. This section is a hands-on guide; the complete list of endpoints is in the [REST API reference](../api-and-runtime/rest-api.md).

## What you can do

- **Ask the agent a question** and get the answer as JSON, or receive it word by word (streaming).
- **Continue a conversation** across several calls, so the agent remembers the previous messages and files.
- **Upload files** for the agent to analyze and **download** the files it produces.
- **List, rename and delete conversations** and read their messages.
- **Use AION as if it were an OpenAI model**, from any tool that supports the OpenAI Chat Completions API.

## Base URL

All paths in this guide are relative to the base URL of your installation:

| Installation | Base URL |
|---|---|
| Docker / standard installation | `https://<your domain>/api` (or `http://localhost/api` when installed without a domain) |
| Developer setup (backend run directly) | `http://localhost:8001` |

So `POST /v1/chat` means `POST https://aion.example.com/api/v1/chat`. A quick check that the URL is right: `GET /health` answers `{"status": "ok", "service": "aion-api"}` without authentication.

The examples in this guide read the address and the API key from two variables, `AION_URL` and `AION_API_KEY`. Set them once in your terminal, replacing the example values with yours:

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

<Tabs groupId="os">
<TabItem value="windows" label="Windows (PowerShell)" default>

```powershell
$env:AION_URL = "https://aion.example.com/api"
$env:AION_API_KEY = "aion_ab12cd34_..."
```

</TabItem>
<TabItem value="unix" label="Linux / macOS (bash)">

```bash
export AION_URL="https://aion.example.com/api"
export AION_API_KEY="aion_ab12cd34_..."
```

</TabItem>
</Tabs>

They stay valid until you close the terminal. Python and JavaScript examples read the same variables from the environment.

## Authentication in short

Programs authenticate with an **API key** (`aion_…`), sent in either header:

```http
Authorization: Bearer aion_ab12cd34_...
X-Api-Key: aion_ab12cd34_...
```

- A key belongs to **one user** and acts **as that user**: it sees their conversations and can use only the profiles they are allowed to use.
- A key has **scopes** that limit what it can do: `chat`, `conversations:read`, `conversations:write`, `files:read`, `files:write`.
- Keys always expire (the maximum lifetime is set by the administrator) and can be revoked at any time.
- Administrative endpoints (`/admin/*`) never accept API keys.

How to get one: [Get an API key](./get-an-api-key.md). For integrations that must not depend on a person, ask the administrator for a [service account](../security/service-accounts.md).

## Which endpoint should I use?

| You want… | Use | Guide |
|---|---|---|
| The simplest possible call: send a message, wait, get the answer as JSON | `POST /v1/chat` | [Your first API call](./first-api-call.md) |
| Show the answer while it is generated, see tool activity, stop a turn | `POST /v1/chat/stream` (Server-Sent Events) | [Streaming responses](./streaming.md) |
| Plug AION into software that already speaks the OpenAI API | `POST /v1/chat/completions`, `GET /v1/models` | [OpenAI-compatible API](./openai-compatible.md) |
| Upload files, list or manage conversations, read history | `/v1/conversations/*` | [Conversations and files](./conversations-and-files.md) |
| A no-code workflow | n8n HTTP node on `POST /v1/chat` | [n8n](../clients/n8n.md) |
| Embed a chat widget in a web page | JavaScript SDK | [SDK and widget](../clients/sdk-and-widget.md) |

## Things worth knowing

- **Profiles.** Every request runs with a profile (the "kind" of agent). If you don't send one, `aion_std` is used. List the profiles your key can use with `GET /profiles` (the `slug` field is the value to send).
- **Conversations.** Without a `conversation_id` each call starts a new conversation. Reuse the id returned by the first call to continue it. Conversations created through the API appear in the user's chat sidebar too.
- **Answers take time.** A turn can last from a few seconds to several minutes when the agent uses many tools. Set generous client timeouts (the synchronous endpoint waits up to 300 seconds by default).
- **Compatibility.** Within a release line, changes are additive: new fields, new event types. Your client must **ignore fields and event types it does not know**. The stable routes are listed in [API contract and deprecation](../api-and-runtime/rest-api.md#api-contract-and-deprecation).
- **Interactive schema.** If enabled on your server (`AION_API_DOCS_ENABLED=1`), the OpenAPI schema is served at `/openapi.json`; every GitHub release also ships it as `openapi.json`.

Problems? See [Errors and troubleshooting](./errors-and-troubleshooting.md).

---
sidebar_position: 3
title: Your first API call
description: Send a message to the agent and read the answer with curl, PowerShell, Python and JavaScript; continue a conversation; choose a profile and options.
---

# Your first API call

This page shows the simplest way to talk to the agent from code: `POST /v1/chat` sends one message, waits until the agent has finished (tools included) and returns the whole answer as JSON. It is ideal for scripts, scheduled jobs and automation tools. You need an API key with the **Chat** permission ([how to get one](./get-an-api-key.md)) and the base URL of your installation ([see API overview](./overview.md#base-url)).

## Send a message

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

<Tabs groupId="lang">
<TabItem value="curl" label="curl" default>

```bash
curl -s "$AION_URL/v1/chat" \
  -H "Authorization: Bearer $AION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "List three ideas to reduce printing costs in an office."}'
```

</TabItem>
<TabItem value="powershell" label="PowerShell">

```powershell
$headers = @{ Authorization = "Bearer $env:AION_API_KEY" }
$body = @{ message = "List three ideas to reduce printing costs in an office." } | ConvertTo-Json

$r = Invoke-RestMethod -Method Post -Uri "$env:AION_URL/v1/chat" `
  -Headers $headers -ContentType "application/json; charset=utf-8" -Body $body `
  -TimeoutSec 600
$r.text
```

</TabItem>
<TabItem value="python" label="Python">

```python
import os
import requests  # pip install requests

AION_URL = os.environ["AION_URL"]
HEADERS = {"Authorization": f"Bearer {os.environ['AION_API_KEY']}"}

resp = requests.post(
    f"{AION_URL}/v1/chat",
    headers=HEADERS,
    json={"message": "List three ideas to reduce printing costs in an office."},
    timeout=600,  # the agent may use tools for a while: be generous
)
resp.raise_for_status()
data = resp.json()
print(data["text"])
print("conversation:", data["conversation_id"])
```

</TabItem>
<TabItem value="js" label="JavaScript (Node 18+)">

```js
const AION_URL = process.env.AION_URL;
const headers = {
  Authorization: `Bearer ${process.env.AION_API_KEY}`,
  "Content-Type": "application/json",
};

const resp = await fetch(`${AION_URL}/v1/chat`, {
  method: "POST",
  headers,
  body: JSON.stringify({ message: "List three ideas to reduce printing costs in an office." }),
});
if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);
const data = await resp.json();
console.log(data.text);
console.log("conversation:", data.conversation_id);
```

</TabItem>
</Tabs>

:::warning Never call AION with an API key from a web page
Code running in a browser exposes the key to anyone who opens the page. Call AION from your backend, or use the [chat widget](../clients/sdk-and-widget.md).
:::

## The response

```json
{
  "text": "1. Set double-sided printing as the default...",
  "conversation_id": "5b0e7c1e-3f0a-4f5e-9d8a-2a7c1d9e4b10",
  "session_id": "5b0e7c1e-3f0a-4f5e-9d8a-2a7c1d9e4b10",
  "profile": "aion_std",
  "success": true,
  "charts": []
}
```

| Field | Meaning |
|---|---|
| `text` | The final answer of the agent (Markdown). |
| `conversation_id` / `session_id` | The conversation the message was saved in (same value). Keep it to continue. |
| `profile` | The profile that answered. |
| `success` | `false` when the turn ended with an error; `error` then explains why. |
| `charts` | Charts generated during the turn, if any (see [Session charts](../api-and-runtime/session-charts.md)). |

## Continue the conversation

Send the `conversation_id` you received: the agent sees the previous messages, the files and the results of earlier tools.

```bash
curl -s "$AION_URL/v1/chat" \
  -H "Authorization: Bearer $AION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "Expand the second idea with an estimate of savings.",
       "conversation_id": "5b0e7c1e-3f0a-4f5e-9d8a-2a7c1d9e4b10"}'
```

You only send the **new** message; AION keeps the history. The conversation also appears in the user's chat sidebar, so you can open it in the browser to see what happened, tools included.

## Choose a profile and options

```json
{
  "message": "How many 5xx errors did the API gateway have in the last hour?",
  "profile": "infra_sre",
  "thinking_enabled": false,
  "web_search_enabled": false,
  "timeout_seconds": 600
}
```

| Field | Default | Meaning |
|---|---|---|
| `message` | — (required) | The text of your message. |
| `conversation_id` | new conversation | Continue an existing conversation. |
| `profile` | `aion_std` | Which agent profile answers. The list your key can use: `GET /profiles` (the `slug` field). |
| `timeout_seconds` | `300` | How long to wait (1–3600). After that you get `504`. |
| `thinking_enabled` | profile default | `false` for faster answers on models that "think". |
| `reasoning_effort` | profile default | How much the model thinks, when thinking is on (see the [REST reference](../api-and-runtime/rest-api.md)). |
| `web_search_enabled` | server default | Allow or forbid web search for this turn. |
| `message_source` | `internal_trigger` | Who started the turn: keep the default for automations, use `user_input` when the text was typed by a person. |

## Use it from n8n, Power Automate and similar tools

Any tool with a generic HTTP request action works: method `POST`, URL `<base URL>/v1/chat`, header `Authorization: Bearer <key>`, JSON body as above, and a timeout of several minutes. Read the answer from `text`. A ready-made n8n setup is described in [n8n](../clients/n8n.md).

## Next steps

- Show the answer while it is written, and see tool activity: [Streaming responses](./streaming.md).
- Send documents to the agent and download what it produces: [Conversations and files](./conversations-and-files.md).
- Already using the OpenAI SDK? [OpenAI-compatible API](./openai-compatible.md).

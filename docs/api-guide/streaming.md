---
sidebar_position: 4
title: Streaming responses
description: Receive the answer word by word with Server-Sent Events, follow tool activity, stop a turn and reconnect, with Python and JavaScript examples.
---

# Streaming responses

With `POST /v1/chat/stream` the answer arrives **while it is being generated**, as a stream of small events: pieces of text, tool calls starting and ending, the final answer. Use it when a person is waiting for the answer (a chat in your app, a bot) or when you want to show what the agent is doing. The format is standard **Server-Sent Events** (SSE). For simple scripts, the synchronous [`POST /v1/chat`](./first-api-call.md) is easier.

You need an API key with the **Chat** permission.

## How it works

1. **Choose a conversation id.** Unlike `/v1/chat`, the stream needs a `conversation_id` in the request. To start a new conversation, generate one yourself — a UUID is perfect (allowed characters: letters, digits, `-` and `_`, 4–128 characters). If the id does not exist yet, AION creates the conversation.
2. **Send the message** to `POST /v1/chat/stream`. The response is `text/event-stream`.
3. **Read the events** until the stream closes. Each event is a JSON object with a `type`.

## The events you need

| `type` | What to do with it |
|---|---|
| `turn_started` | Always the first event. Contains the ids of the saved user and assistant messages. |
| `token` | Append `content` to the answer you are showing. |
| `reasoning` | The model's "thinking", when the model exposes it. Show it separately or ignore it. |
| `tool_event` | Tool activity: `event.type` is `tool_start` (with `name` and `input`), `tool_end` (with `output`) or `tool_error`. Useful for "Searching the file server…" messages. |
| `final` | The complete final answer in `text`. Prefer it over the concatenated tokens. |
| `error` | Something went wrong; `content` explains what. |

There are more event types (plans, artifacts, context usage). **Ignore any type you don't know**: new types can appear in any release. The full list is in [Chat stream events (SSE)](../api-and-runtime/sse-events.md).

:::note The turn ends when the stream closes
A turn can contain several model calls (one per tool round), so do not stop reading at the first `stream_end`. The reliable signal is the stream closing. Normally `final` is the last event.
:::

A raw stream looks like this:

```text
: aion-open

event: message
data: {"type": "turn_started", "user_message_id": "…", "assistant_message_id": "…"}

event: message
data: {"type": "tool_event", "event": {"type": "tool_start", "id": "call-1", "name": "web_search", "input": {"query": "…"}}}

event: message
data: {"type": "token", "content": "According to "}

event: message
data: {"type": "final", "text": "According to the latest data…"}
```

Lines starting with `:` are comments (the stream opener and keep-alive pings every 15 seconds): skip them.

## Examples

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

<Tabs groupId="lang">
<TabItem value="python" label="Python" default>

```python
import json
import os
import uuid

import requests  # pip install requests

AION_URL = os.environ["AION_URL"]
HEADERS = {"Authorization": f"Bearer {os.environ['AION_API_KEY']}"}

conversation_id = str(uuid.uuid4())  # new conversation; reuse it for the next messages
body = {"conversation_id": conversation_id, "message": "What's new in Python 3.13? Search the web."}

with requests.post(f"{AION_URL}/v1/chat/stream", headers=HEADERS, json=body,
                   stream=True, timeout=(10, 900)) as resp:
    resp.raise_for_status()
    final_text = None
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue  # skip blank lines, comments (":") and "event:" lines
        event = json.loads(line[len("data:"):].strip())
        etype = event.get("type")
        if etype == "token":
            print(event["content"], end="", flush=True)
        elif etype == "tool_event" and event["event"].get("type") == "tool_start":
            print(f"\n[tool] {event['event']['name']}…", flush=True)
        elif etype == "final":
            final_text = event["text"]
        elif etype == "error" or "error" in event:
            print("\n[error]", event.get("content") or event.get("error"))

print("\n\nconversation:", conversation_id)
```

</TabItem>
<TabItem value="js" label="JavaScript (Node 18+)">

```js
import { randomUUID } from "node:crypto";

const AION_URL = process.env.AION_URL;
const conversationId = randomUUID(); // new conversation; reuse it for the next messages

const resp = await fetch(`${AION_URL}/v1/chat/stream`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${process.env.AION_API_KEY}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ conversation_id: conversationId, message: "What's new in Python 3.13? Search the web." }),
});
if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);

const decoder = new TextDecoder();
let buffer = "";
for await (const chunk of resp.body) {
  buffer += decoder.decode(chunk, { stream: true });
  let sep;
  while ((sep = buffer.indexOf("\n\n")) >= 0) {        // one SSE frame per blank line
    const frame = buffer.slice(0, sep);
    buffer = buffer.slice(sep + 2);
    for (const line of frame.split("\n")) {
      if (!line.startsWith("data:")) continue;          // skip comments and "event:" lines
      const event = JSON.parse(line.slice(5).trim());
      if (event.type === "token") process.stdout.write(event.content);
      else if (event.type === "tool_event" && event.event.type === "tool_start")
        console.log(`\n[tool] ${event.event.name}…`);
      else if (event.type === "error" || event.error) console.error("\n[error]", event.content ?? event.error);
    }
  }
}
console.log("\n\nconversation:", conversationId);
```

</TabItem>
<TabItem value="curl" label="curl">

```bash
curl -N "$AION_URL/v1/chat/stream" \
  -H "Authorization: Bearer $AION_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"conversation_id\": \"$(uuidgen)\", \"message\": \"Hello!\"}"
```

`-N` disables buffering so events are printed as they arrive.

</TabItem>
</Tabs>

## Useful request fields

The body accepts the same options as [`/v1/chat`](./first-api-call.md#choose-a-profile-and-options) (`profile`, `thinking_enabled`, `reasoning_effort`, `web_search_enabled`…), plus:

| Field | Meaning |
|---|---|
| `conversation_id` | **Required.** Existing conversation, or a new id you generated. |
| `attachments` | Files previously uploaded to the conversation that this message refers to. See [Conversations and files](./conversations-and-files.md#ask-the-agent-about-a-file). |
| `message_source` | Defaults to `user_input` here (a person is typing). |

## Stop a turn

```bash
curl -s -X POST "$AION_URL/v1/chat/stop?conversation_id=$CONVERSATION_ID" \
  -H "Authorization: Bearer $AION_API_KEY"
```

The agent stops as soon as possible; the stream then closes. Whatever was produced so far is saved.

## Lost connection? Reconnect

If your client disconnects while the agent is still working, the turn **continues on the server**. To pick it up again:

```bash
curl -N "$AION_URL/v1/chat/stream/reconnect/$CONVERSATION_ID" \
  -H "Authorization: Bearer $AION_API_KEY"
```

It replays all the events of the running turn from the beginning and then continues live. If the turn has already finished, you get only a `: aion-not-active` comment: read the result from the conversation messages instead (`GET /v1/conversations/{id}/messages`, see [Conversations and files](./conversations-and-files.md)).

## Proxies and timeouts

- Streams can stay open for many minutes. Set read timeouts accordingly and make sure reverse proxies between your client and AION do not buffer responses (the AION Docker stack is already configured for this).
- Keep-alive comments arrive every 15 seconds, so an idle connection is not a sign of a problem.

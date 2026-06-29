---
sidebar_position: 3
title: SDK and Web Widget
description: How to integrate AION Agent into external applications using the official SDKs or the JS widget.
---

# SDK and Web Widget

> [!WARNING]
> The SDKs (Python and TypeScript) and the Web Widget are currently under active development. Some features may not be stable, undergo substantial interface changes, or not function correctly under all conditions. Use them with caution.

To facilitate the adoption of AION Agent in different ecosystems, official SDKs are available for Python and TypeScript, in addition to a "drop-in" widget for websites.

## Python SDK

The Python SDK allows for programmatic interaction with AION, ideal for backend automations or integrations into other Python services.

### Installation
```bash
pip install ./sdk/python
```

### Usage example
```python
from aion_client import AionClient

client = AionClient(
    base_url="https://aion.example.com",
    api_key="aion_your_key_here"
)

# Start a conversation
conv = client.conversations.create(
    profile="aion_std",
    user_id="user_123"
)

# Chat in streaming
for event in client.chat.stream(conv.id, "Hello, how can you help me?"):
    if event.type == "token":
        print(event.content, end="", flush=True)
```

---

## TypeScript / JavaScript SDK

Ideal for modern web applications (React, Vue, Node.js).

### Installation
```bash
npm install ./sdk/typescript
```

### Usage example
```typescript
import { AionClient } from '@aion/client';

const client = new AionClient({
  baseUrl: 'https://aion.example.com',
  apiKey: 'aion_your_key_here'
});

const stream = client.chat.stream({
  conversationId: '...',
  message: 'Analyze the file report.csv'
});

for await (const event of stream) {
  if (event.type === 'token') {
    process.stdout.write(event.content);
  }
}
```

---

## Web Widget (Drop-in)

The widget allows you to add an AION chat to your website with a few lines of code.

### Inclusion
```html
<script src="https://aion.example.com/static/widget/aion-widget.js"></script>
<script>
  AionWidget.init({
    baseUrl: 'https://aion.example.com',
    apiKey: 'aion_public_widget_key',
    profile: 'aion_std',
    user: { id: 'anonymous-user' },
    theme: 'dark'
  });
</script>
```

### Widget Security
When you expose a widget publicly, make sure that the API Key used has the limited scope `chat:scoped`. This prevents malicious users from accessing other people's conversations.

---

## Recommended patterns

1. **Error Handling**: Both SDKs automatically handle exponential retries on transient errors (5xx, 429).
2. **Large files**: The SDKs automatically detect if a file exceeds the direct upload threshold and autonomously switch to the **Presigned PUT** flow to ensure stability with large files.
3. **Cancellation**: Use the `.stop()` method of the SDK to send the interruption signal if the user closes the window or cancels the client-side operation.

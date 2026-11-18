---
sidebar_position: 5
title: Conversations and files
description: Upload documents for the agent, ask about them, download the files it creates, and list, rename, read and delete conversations.
---

# Conversations and files

Every conversation has its own private folder (the *workspace*) where your uploads and the files created by the agent live. This page shows the typical flows: send a document and ask about it, download a report the agent generated, and manage conversations (list, read messages, rename, delete). Each step says which API key permission it needs.

## The conversation folder

| Folder | Content |
|---|---|
| `uploads/` | Files you uploaded. |
| `workspace/` | Files the agent created (reports, Word documents, CSV, charts…). |
| `derived/` | Files AION derived automatically, for example a `.docx` converted from an old `.doc` upload. |

Files are always addressed by their **relative path**, such as `uploads/3f9a1c2b_offer.pdf` or `workspace/report.docx`.

## Ask the agent about a file

Permissions: **Upload files** + **Chat**.

**1. Upload the file** with a multipart request (field name `files`, repeatable for several files). The conversation is created if it does not exist, so you can use a fresh UUID:

```bash
CONVERSATION_ID=$(uuidgen)
curl -s "$AION_URL/v1/conversations/$CONVERSATION_ID/files" \
  -H "Authorization: Bearer $AION_API_KEY" \
  -F "files=@offer.pdf"
```

```json
{
  "attachments": [
    {
      "relative_path": "uploads/3f9a1c2b_offer.pdf",
      "original_relative_path": "uploads/offer.pdf",
      "name": "3f9a1c2b_offer.pdf",
      "original_name": "offer.pdf",
      "size_bytes": 482113,
      "mime": "application/pdf"
    }
  ]
}
```

**2. Ask about it** with the streaming endpoint, passing the returned objects in `attachments` so the agent knows which files the message refers to:

```bash
curl -N "$AION_URL/v1/chat/stream" \
  -H "Authorization: Bearer $AION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "'"$CONVERSATION_ID"'",
    "message": "Summarize this offer: price, duration and penalties.",
    "attachments": [{"relative_path": "uploads/3f9a1c2b_offer.pdf", "original_name": "offer.pdf", "mime": "application/pdf"}]
  }'
```

How to read the stream: [Streaming responses](./streaming.md).

The same flow in Python:

```python
import os, uuid, json, requests

AION_URL = os.environ["AION_URL"]
HEADERS = {"Authorization": f"Bearer {os.environ['AION_API_KEY']}"}
conv = str(uuid.uuid4())

# 1. upload
with open("offer.pdf", "rb") as fh:
    up = requests.post(f"{AION_URL}/v1/conversations/{conv}/files",
                       headers=HEADERS, files=[("files", ("offer.pdf", fh, "application/pdf"))], timeout=120)
up.raise_for_status()
attachments = up.json()["attachments"]

# 2. ask, reading the streamed answer
body = {"conversation_id": conv, "message": "Summarize this offer: price, duration and penalties.",
        "attachments": attachments}
with requests.post(f"{AION_URL}/v1/chat/stream", headers=HEADERS, json=body, stream=True, timeout=(10, 900)) as r:
    r.raise_for_status()
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith("data:"):
            ev = json.loads(line[5:].strip())
            if ev.get("type") == "final":
                print(ev["text"])
```

:::note
The synchronous `POST /v1/chat` has no `attachments` field: to point the agent at specific files, use `POST /v1/chat/stream`.
:::

Large PDFs, scanned documents and old Word files are processed automatically after upload (text extraction, OCR, `.doc` → `.docx` conversion). See [Office and legacy Word](../configuration/office-and-legacy-word.md) and [Document evidence](../configuration/document-evidence.md).

## Download the files the agent produced

Permission: **Read files**.

**1. List the files** of a folder (`uploads`, `workspace` or `derived`):

```bash
curl -s "$AION_URL/sessions/$CONVERSATION_ID/files?subdir=workspace" \
  -H "Authorization: Bearer $AION_API_KEY"
```

```json
{"files": [{"name": "offer_summary.docx", "relative_path": "workspace/offer_summary.docx", "size_bytes": 18234, "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}]}
```

`GET /v1/conversations/{id}/files` returns the same information for `uploads/` only.

**2. Download** one file by relative path:

```bash
curl -s -o offer_summary.docx \
  "$AION_URL/sessions/$CONVERSATION_ID/download?relative_path=workspace/offer_summary.docx" \
  -H "Authorization: Bearer $AION_API_KEY"
```

```powershell
Invoke-WebRequest -OutFile offer_summary.docx -Headers @{ Authorization = "Bearer $env:AION_API_KEY" } `
  -Uri "$env:AION_URL/sessions/$env:CONVERSATION_ID/download?relative_path=workspace/offer_summary.docx"
```

## Manage conversations

| Task | Request | Permission |
|---|---|---|
| Create a conversation with a title, tags or metadata | `POST /v1/conversations` with `{"profile": "aion_std", "title": "Q2 audit", "tags": ["audit"], "metadata": {"source": "crm"}}` | Manage conversations |
| List your conversations | `GET /v1/conversations?limit=20` | Read conversations |
| Read one conversation | `GET /v1/conversations/{id}` | Read conversations |
| Read its messages | `GET /v1/conversations/{id}/messages?limit=50` (`include_internal=true` adds tool messages) | Read conversations |
| Rename, retag | `PATCH /v1/conversations/{id}` with `{"title": "…", "tags": […]}` | Manage conversations |
| Delete (archive) | `DELETE /v1/conversations/{id}` | Manage conversations |

Creating a conversation explicitly is optional: `POST /v1/chat` creates one when you omit the id, and `POST /v1/chat/stream` creates it on first use. Create it explicitly when you want a title, tags or metadata (for example the id of the CRM ticket that originated it), so you can find it later.

Example — read the last messages of a conversation:

```bash
curl -s "$AION_URL/v1/conversations/$CONVERSATION_ID/messages?limit=10" \
  -H "Authorization: Bearer $AION_API_KEY"
```

```json
{"data": [
  {"id": "…", "role": "user", "content": "Summarize this offer…", "created_at": "2026-11-18T09:12:03Z"},
  {"id": "…", "role": "assistant", "content": "The offer is valid for 24 months…", "reasoning": null, "created_at": "2026-11-18T09:12:41Z"}
]}
```

## Ownership and privacy

- A conversation belongs to the user who created it (for a key: the key's owner). Every other user — administrators included — gets `404 Conversation not found`, so its existence is not revealed.
- Conversations created through the API show up in the owner's chat sidebar, where they can be continued by hand.
- Deleting a conversation archives it and frees the resources the agent was keeping for it.

Full request and response schemas: [REST API reference](../api-and-runtime/rest-api.md).

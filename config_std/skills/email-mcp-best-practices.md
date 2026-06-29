---
description: 'Operational guide for effective Email MCP tools: filters, multiple folders, dates, and threads.'
name: email-mcp-best-practices
source: curated
status: verified
tags:
- email
- mcp
- imap
- best-practices
version: 1
---

# Email MCP Best Practices

## When to activate
Use this skill whenever the user asks to read, search, send, or manage email via MCP tools (`list_emails`, `search_emails`, `send_email`, etc.).

## Standard workflow
1. **Verify accounts**: `list_accounts` to discover configured accounts.
2. **Explore folders**: `list_mailboxes` to see available folders (INBOX, Drafts, Sent, Trash, etc.).
3. **Targeted search**:
   - Use `search_emails` for specific keywords.
   - Use `list_emails` for chronological lists or advanced filters (dates, attachments, read state).
4. **Detailed read**: `get_email` or `get_emails` (batch up to 20) for message bodies.
5. **Thread handling**: `get_thread` to reconstruct full conversations.

## Common pitfalls and fixes
- **Hidden filters**: `list_emails` applies default filters that may hide read or unread mail. If the user asks for "all mail from yesterday", remove restrictive filters or run separate calls with `seen=true` and `seen=false`.
- **Multiple folders**: Inbound and sent mail often live in different folders (e.g. `INBOX` vs `Sent`). Always check both when requested.
- **Pagination**: Set a high `pageSize` (e.g. 50–100) and manage `page` to avoid missing messages.
- **ISO 8601 dates**: Use precise formats for `since` and `before`. Watch time zones (UTC by default).
- **ProtonMail/Gmail**: Labels/folders may behave differently. Use `list_labels` or `list_mailboxes` to map structure.

## Key tools
| Tool | Primary use |
|-----------|----------------|
| `list_emails` | Chronological list with filters (state, dates, attachments) |
| `search_emails` | Full-text keyword search |
| `get_email` / `get_emails` | Fetch body and metadata |
| `get_thread` | Reconstruct conversation (References/In-Reply-To) |
| `send_email` / `reply_email` / `forward_email` | Outbound handling |
| `mark_email` / `move_email` / `delete_email` | Cleanup and organization |

## Pro tips
- For quick analysis, use `get_emails` with `format="text"` for HTML stripping and compact output.
- Before destructive actions (move/delete), verify the real folder with `find_email_folder` if the message comes from virtual folders.
- Keep a professional, privacy-first tone: never share sensitive content the user did not ask for.

---
name: email_imap_mcp
description: "Use IMAP/SMTP MCP tools (search_emails, send_email, list_folders) when the profile includes email-mcp-server."
tags: [email, imap, mcp]
status: verified
source: curated
version: 1
---

# Email MCP (IMAP / SMTP)

## When this applies
Use this skill when the active profile includes the **email-mcp-server** MCP and those tools appear in your tool list.

## Golden rules
1. **Do not claim you lack mailbox access** if `search_emails`, `send_email`, or `list_folders` are available—call them.
2. **Credentials**: If the user has not configured integration in chat-ui, tell them to open **My integrations** and complete EMAIL_USER, EMAIL_PASSWORD, IMAP/SMTP host and ports.
3. **Privacy**: Summarize email content for the user; do not exfiltrate unrelated messages.

## Tool usage
| Tool | Purpose |
|------|---------|
| `search_emails` | Search INBOX or another folder; use `query` (e.g. `unseen`, `from`, `subject`) and `limit`. |
| `send_email` | Send mail: `to`, `subject`, `text` (optional `html`). |
| `list_folders` | List mailboxes before searching less common folders. |

Typical flow for "read my mail":
1. `list_folders` if folder is unclear.
2. `search_emails` with `folder: INBOX`, sensible `limit`, and `query` (e.g. recent/unseen).
3. Present subjects, from, date; offer to search with narrower criteria if needed.

## Errors
If a tool returns an authentication or connection error, report it clearly and suggest checking credentials in chat-ui integrations—not that you "cannot access email" in general.

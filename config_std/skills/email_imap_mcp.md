---
name: email_imap_mcp
description: "Use IMAP/SMTP MCP tools (search_emails, get_emails_content, download_attachment, send_email, list_folders) when the profile includes email-mcp-server."
tags: [email, imap, mcp, attachments]
status: verified
source: curated
version: 2
---

# Email MCP (IMAP / SMTP & Attachments)

## When this applies
Use this skill when the active profile includes the **email-mcp-server** MCP and those tools appear in your tool list.

## Golden rules
1. **Do not claim you lack mailbox access** if `search_emails`, `get_emails_content`, `send_email`, or `list_folders` are available—call them.
2. **Attachments and `save_path`**: When calling `download_attachment`, always specify `save_path: "uploads/<filename>"` (e.g. `save_path: "uploads/document.docx"`). Files downloaded to `uploads/` are immediately accessible in the session sandbox for reading, unpacking, or OCR.
3. **Reading downloaded documents**: After downloading to `uploads/<filename>`, use the appropriate tools for the file type:
   - **DOCX**: unpack with `scripts/office/unpack.py uploads/<file>.docx workspace/unpacked` or read XML.
   - **PDF / images**: use OCR or standard document extraction tools.
   - **Text / CSV / JSON**: use `sandbox_read_text_file(relative_path="uploads/<file>")`.
4. **Credentials**: If the user has not configured integration in chat-ui, tell them to open **My integrations** and complete EMAIL_USER, EMAIL_PASSWORD, IMAP/SMTP host and ports.
6. **`list_emails_metadata` does NOT populate attachments**: `list_emails_metadata` only fetches IMAP header metadata and **always returns `attachments: []`**. You **MUST ALWAYS** call `get_emails_content(email_ids=["<id>"])` to inspect the actual list of attachments and message body. Never state that an email has no attachments based only on `list_emails_metadata`.

## Tool usage
| Tool | Purpose |
|------|---------|
| `list_emails_metadata` / `search_emails` | Search INBOX or another folder to find message IDs (`email_id`). Note: `attachments` in metadata is always empty. |
| `get_emails_content` | **Retrieve body and the real list of attachments** for specific `email_id` values. |
| `download_attachment` | Download an email attachment. **Always pass `save_path: "uploads/<filename>"`**. |
| `send_email` | Send mail: `to`, `subject`, `text` (optional `html`). |
| `list_folders` | List mailboxes before searching less common folders. |

## Typical Flows

### 1. Read recent emails
1. `list_folders` if folder is unclear.
2. `list_emails_metadata` or `search_emails` with sensible limit.
3. Present subjects, sender, date; retrieve full body via `get_emails_content` when requested.

### 2. Read and analyze email attachments
1. Use `list_emails_metadata` to find the target `email_id` (e.g. latest email).
2. **Always call `get_emails_content(email_ids=["<email_id>"])`** to inspect the message body and the actual `attachments: [...]` list (since `list_emails_metadata` does not list attachments).
3. Call `download_attachment(email_id="<email_id>", attachment_name="<name>", save_path="uploads/<name>")` for the relevant document (ignoring signature images like `image001.png` unless relevant).
4. For DOCX, unpack with `scripts/office/unpack.py uploads/<name> workspace/unpacked` and read `workspace/unpacked/word/document.xml`.
5. For other formats, use standard reading tools (`sandbox_read_text_file`, OCR, etc.).

## Errors
If a tool returns an authentication or connection error, report it clearly and suggest checking credentials in chat-ui integrations—not that you "cannot access email" in general.


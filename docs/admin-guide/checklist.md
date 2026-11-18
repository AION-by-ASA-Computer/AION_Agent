---
sidebar_position: 1
title: Administrator checklist
description: The tasks to complete to put AION into service for your company, in order, with a link to the detailed page for each.
---

# Administrator checklist

This page is the to-do list for whoever runs AION for a company: from the first login to the day users start working with it. Each step says what to do, where in the **admin panel** (`/admin`) to do it, and links to the detailed page. Steps marked *optional* can be skipped and done later.

## 1. Install and secure the server

- [ ] Install AION with the installer or Docker Compose, with your **domain** so HTTPS is configured automatically. → [Quickstart](../getting-started/quickstart.md), [Deploy with Docker](../deployment/docker.md)
- [ ] Sign in to the admin panel as `admin` / `admin` and **change the password** immediately.
- [ ] Keep a copy of the `.env` file in a safe place: it contains the encryption key for the stored credentials (`AION_CREDENTIAL_ENCRYPTION_KEY`). Without it, a restored backup cannot decrypt users' credentials.

## 2. Connect the AI model

- [ ] Complete the **First setup** wizard, or later **Settings → LLM**: provider, key, **Test connection**, model. → [LLM provider precedence](../configuration/llm-provider-precedence.md)
- [ ] *Optional:* embeddings (better memory and document search), remote **OCR** (scanned documents), **web search** provider (Tavily, Brave, SearXNG), **speech-to-text** for voice messages. → [Speech-to-text](../mcp/speech-to-text.md), [Web search](../configuration/web-search-and-fetch.md)

## 3. Set up email

- [ ] **Settings → SMTP**: configure the outgoing mail server and send a test email. AION uses it for invitations and password resets, so administrators never see users' passwords. Without SMTP, AION shows a one-time temporary password instead. → [Password setup by email](../security/password-setup-email.md)

## 4. Decide how people sign in

- [ ] **Password** (default), **Microsoft** or **Google** single sign-on. Switching to SSO starts a guided migration of existing accounts. → [SSO migration](../security/sso-migration.md)
- [ ] With SSO, choose who can create an account at first login: everybody, an allow-list of emails/domains, or nobody.
- [ ] *Optional:* require **two-factor authentication** (authenticator app) for password logins. → [Two-factor authentication](../security/two-factor-auth.md)

## 5. Create users

- [ ] **Users**: with password login, enter name and email; the user receives an invitation link. With SSO, accounts are created at first sign-in.
- [ ] Give the **admin** role only to people who must manage AION.
- [ ] Restrict **profiles** per user if some agents should be available only to some teams.
- [ ] Enable **Can create API keys** only for users who build integrations, and set quota and maximum lifetime. → [Get an API key](../api-guide/get-an-api-key.md)
- [ ] For integrations that must not depend on a person, create a **service account**. → [Service accounts](../security/service-accounts.md)

## 6. Choose the agents (profiles) and their knowledge

- [ ] **Profiles**: review the standard profiles, decide which ones to offer, adapt the instructions to your company (tone, language, rules). → [Profiles](../configuration/profiles.md)
- [ ] **Skills**: add written procedures the agent should follow (e.g. how to prepare your monthly report). → [Skills and prompts](../configuration/skills-and-prompts.md)

## 7. Connect company systems

- [ ] **MCP Hub**: enable the connectors you need, choose for each whether it uses a **shared company account** or **each user's own credentials**. → [MCP registry](../mcp/registry.md), [Connector catalog](../mcp/connector-catalog.md), [Credentials and isolation](../mcp/user-isolation-and-credentials.md)
- [ ] *Optional:* **Windows file shares** — add servers and shares in **Settings → File server**; users enter their Windows credentials. → [Windows file shares](../mcp/smb-files.md)
- [ ] *Optional:* **Microsoft 365** → [Microsoft 365](../mcp/microsoft-365.md)
- [ ] *Optional:* **your own systems** (CRM, ERP, internal tools): enable **Settings → MCPs → Upload enabled** and import the MCP servers developed by your team. → [Custom MCP servers](../mcp/custom-mcp-servers.md)
- [ ] Review the **filesystem policy** (what the agent may read or write on the server). → [Filesystem policy](../configuration/filesystem-policy-and-promo.md)

## 8. Optional channels

- [ ] **WhatsApp** (Meta Cloud API) → [WhatsApp channel](../integrations/whatsapp.md)
- [ ] **Telegram** → [Telegram channel](../telegram/RUNBOOK.md)

## 9. Run it day to day

- [ ] **Updates**: when a new version is out, the admin panel shows a banner; with the updater enabled, **Update now** applies it with an automatic backup and rollback. → [Self-update](../deployment/self-update.md)
- [ ] **Backups** of the data volume (database, conversations, files, memory). → [Deploy with Docker](../deployment/docker.md)
- [ ] **Monitoring**: **System** and **Diagnostics** pages for service health; **Metrics** and **Feedback** to see usage and answer quality; **Security** for the audit log. → [Observability](../architecture/observability.md)
- [ ] Tell users where to start: share [Using the chat](../user-guide/using-the-chat.md).

## Where things are in the admin panel

| Page | Use it to |
|---|---|
| **Users** / **Service accounts** | Accounts, roles, profile access, API key policy, password links. |
| **Profiles** / **Skills** | The agents and the procedures they follow. |
| **MCP Hub** | Connectors (tools), their credentials and availability. |
| **Memory** | Memory projects and their members. |
| **Schedules** | Scheduled jobs across users. |
| **Settings** | LLM, embeddings, OCR, audio, web search, SMTP, file server, sign-in mode. |
| **Security** | Audit log and security posture. |
| **System** / **Diagnostics** / **Metrics** / **Feedback** | Health, troubleshooting, usage, quality. |
| **WhatsApp** / **Telegram** | Messaging channels. |

Full description of each page: [Admin UI](../clients/admin-ui.md).

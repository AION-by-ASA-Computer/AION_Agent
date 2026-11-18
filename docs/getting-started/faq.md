---
sidebar_position: 4
title: FAQ
description: Short answers to the most common questions about AION - data, models, costs, access, API and troubleshooting.
---

# Frequently asked questions

Short answers to the questions people ask most often, for users, administrators and IT staff. Each answer links to the page with the details.

## General

**Which AI model does AION use?**
The one your company chooses: AION is not tied to a specific model, and the administrator configures it. → [LLM provider precedence](../configuration/llm-provider-precedence.md)

**Does our data leave the company?**
Conversations, files and memory stay on your server. To answer, each request is processed by the AI model your company has chosen. Web search, when enabled, sends search queries to the search provider. → [What is AION](./what-is-aion.md#is-my-data-safe)

**Can administrators read my conversations?**
No. The admin panel has no access to conversation content, and the API returns "not found" for conversations belonging to someone else.

**Can we connect AION to our own applications?**
Yes. Besides the ready-made connectors, your developers can write their own MCP server in Python and an administrator imports it from the admin panel; it runs isolated, with the network closed by default. → [Custom MCP servers](../mcp/custom-mcp-servers.md)

**Is AION open source?**
Yes, the repository is public on GitHub. → [Repository model](../opensource/repository-model.md)

## Using the chat

**The agent says it cannot access a system (file server, Microsoft 365…).**
Usually your personal credentials are missing or expired: open **Integrations** in the sidebar. If the connector is not listed, ask your administrator to enable it for your profile.

**Why don't I see a profile or an option that a colleague has?**
Administrators decide which profiles, tools and features each user gets.

**The answer is slow.**
The agent may be using many tools or thinking at high effort. Lower **Thinking**, turn off **Web search** if not needed, or split the request.

## API and integrations

**How do I call AION from a script?**
Ask your administrator to enable API keys for you, create a key in **Settings → API keys**, then follow [Your first API call](../api-guide/first-api-call.md).

**Can I use the OpenAI SDK or tools such as Open WebUI?**
Yes: point them at `<base URL>/v1` with an AION key; profiles appear as models. → [OpenAI-compatible API](../api-guide/openai-compatible.md)

**My integration should keep working when I leave the company.**
Use a service account instead of a personal key. → [Service accounts](../security/service-accounts.md)

**Where is the full list of endpoints?**
In the [REST API reference](../api-and-runtime/rest-api.md); the OpenAPI schema is attached to each GitHub release and served at `/openapi.json` when enabled.

## Administration and operations

**How do I update AION?**
From the admin panel (**Update now**) or with the installer's `upgrade` command; both make a backup and roll back if something fails. → [Self-update](../deployment/self-update.md)

**Can I run several backend workers to scale?**
No: the backend must run with a single worker, because it keeps per-conversation state in memory. Scale vertically, or use separate installations. → [Deploy with Docker](../deployment/docker.md)

**A user is locked out.**
Send a new password link from **Users**. For two-factor problems an administrator can reset the user's 2FA. If the only administrator is locked out, use the recovery command described in [SSO migration](../security/sso-migration.md) and [Two-factor authentication](../security/two-factor-auth.md).

**Where do I find logs?**
`docker compose logs -f backend` from the installation folder (add `-f docker-compose.ghcr.yml` for installer-based setups), plus the **System** and **Diagnostics** pages in the admin panel. → [Observability](../architecture/observability.md)

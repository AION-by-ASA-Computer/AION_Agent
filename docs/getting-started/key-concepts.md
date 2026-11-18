---
sidebar_position: 2
title: Key concepts
description: The words you will meet in AION and in this documentation (profile, skill, connector, conversation, memory, API key…), explained simply.
---

# Key concepts

This page is a small glossary. Each term is explained in one or two sentences, with a link to the page that covers it in depth. If a word in the rest of the documentation is unclear, it is probably here.

## Using the agent

| Term | What it means |
|---|---|
| **Agent** | The AI assistant. Unlike a plain chatbot, it can call *tools* to fetch information or perform actions, then answer using the results. |
| **Profile** | A ready-made "version" of the agent for a job: its instructions, the tools it can use and, optionally, the AI model. Examples: `aion_std` (general assistant), `file_server_assistant`, `infra_sre`. You pick it in the chat; in the API it is the `profile` field (or `model` in the OpenAI-compatible API). → [Profiles](../configuration/profiles.md) |
| **Skill** | A short written procedure the agent can read when needed (for example "how to build a monthly report"). Skills teach the agent *how* to do something; tools give it the *means*. → [Skills and prompts](../configuration/skills-and-prompts.md) |
| **Tool** | A single action the agent can perform, such as reading a file, searching the web or querying Prometheus. In the chat you can see which tools were used for each answer. |
| **Connector (MCP server)** | A plug-in that provides a group of tools for one system (file server, Microsoft 365, a database…). MCP (Model Context Protocol) is the open standard used to plug them in. Your developers can also build their own. → [MCP registry](../mcp/registry.md), [Custom MCP servers](../mcp/custom-mcp-servers.md) |
| **Conversation / session** | One chat thread. It has an id, its history and its own **workspace**: a private folder with the files you upload and the files the agent creates. In the API, `conversation_id` and `session_id` are the same thing. |
| **Turn** | One question from you plus the complete answer from the agent, including all the tool calls in between. |
| **Thinking (reasoning)** | Some AI models "think" before answering. In the chat you can choose how much (off, minimal, medium, maximum): more thinking is slower but better for hard problems. |
| **Streaming** | The answer appears word by word while it is generated, instead of all at the end. The API offers both modes. |

## Memory

| Term | What it means |
|---|---|
| **Short-term memory (STM)** | The recent messages of the current conversation that are sent to the AI model at each turn. When the conversation gets long, older parts are summarized (*compaction*) so it fits. → [Context compaction](../memory/context-compaction.md) |
| **Long-term memory (LTM)** | Facts the agent learns about you across conversations (preferences, recurring information) and reuses later. → [Memory overview](../memory/stm-ltm-and-query.md) |
| **Instructions (USER.md)** | Personal instructions you write in the chat settings ("answer in Italian", "I work in the finance team"), added to every conversation. → [SOUL, MEMORY and USER](../configuration/soul-memory-user.md) |
| **Query memory / project** | A shared catalogue of validated database queries, grouped by *project* (for example `sales`), so the agent reuses queries that are known to be correct. |

## Access and security

| Term | What it means |
|---|---|
| **User** | A person with an account. Can sign in with a password or, if enabled, with a Microsoft or Google company account (SSO). |
| **Administrator** | A user with the `admin` role: can open the admin panel and manage users, models, profiles and connectors. |
| **API key** | A secret string (`aion_…`) that lets a program call AION **on behalf of one user**, with limited permissions (*scopes*). → [Get an API key](../api-guide/get-an-api-key.md) |
| **Scope** | A permission attached to an API key: `chat`, `conversations:read`, `conversations:write`, `files:read`, `files:write`. |
| **Service account** | A non-human account (`svc-…`) for integrations that should not depend on a real person. Only administrators create it and its keys. → [Service accounts](../security/service-accounts.md) |
| **Personal credentials** | Usernames, passwords or tokens that *you* enter once in **Integrations** so a connector can act as you (for example your Windows account for the file server). They are stored encrypted. |

## Running AION

| Term | What it means |
|---|---|
| **LLM provider** | The service that gives AION access to an AI model. AION works with the model your company chooses; the administrator configures it. → [LLM provider precedence](../configuration/llm-provider-precedence.md) |
| **chat-ui / admin-ui / backend** | The three main applications: the chat web app, the admin web app and the API server that does the work. |
| **Tenant / instance** | One AION installation for one company, usually reachable on its own domain. |

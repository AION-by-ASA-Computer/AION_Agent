---
slug: /
sidebar_position: 1
title: AION Agent Documentation
description: Index of the technical documentation of the AION Agent project.
---

# AION Agent Documentation

**AION · ASA:** [https://aion-asa.com](https://aion-asa.com)

The source code remains the source of truth. These pages are organized **by functional area** (architecture, configuration, API, clients, memory, MCP, security, learning). The folder structure in `docs/` coincides with the sidebar of the Docusaurus site (`website/`).

## Documentation map

| Area | Content |
|------|-----------|
| [Introduction](./introduction/overview.md) | Context, how to navigate the doc |
| [Architecture](./architecture/overview.md) | End-to-end flow, [source tree](./architecture/source-tree.md), {/* [Agent DB](./architecture/agent-db.md), */} [observability](./architecture/observability.md), [testing and optimization](./architecture/testing-and-optimization.md) |
| [Configuration](./configuration/environment.md) | `.env`, YAML, [profiles](./configuration/profiles.md), [skills](./configuration/skills-and-prompts.md), [SOUL/MEMORY/USER](./configuration/soul-memory-user.md) |
| [Deployment](./deployment/docker.md) | [Docker Compose](./deployment/docker.md): multi-tenant prod stack, customer onboarding. |
| [API and runtime](./api-and-runtime/rest-api.md) | FastAPI/SSE, [agent pipeline](./api-and-runtime/agent-pipeline.md) |
| [Clients](./clients/chat-ui.md) | [Chat UI](./clients/chat-ui.md), [Admin UI](./clients/admin-ui.md), [SDK & Widget](./clients/sdk-and-widget.md) |
| [Memory](./memory/stm-ltm-and-query.md) | STM/LTM, [FTS / session_search](./memory/chat-history-and-fts.md), [Structured Memory](./memory/structured-memory.md) |
| [MCP](./mcp/registry.md) | Registry and servers |
| [Security](./security/identity-and-chat-auth.md) | Identity, chat login, enterprise roadmap |
| [Learning (Hermes)](./learning/hermes-features.md) | Compression, distill, nudge, approval |
| [Standards](./standard/authoring.md) | Conventions for those updating the doc |

**Admin UI:** Next.js dashboard in **`admin-ui/`** (`pnpm dev` → http://localhost:3870). The `static/admin` folder is deprecated for the UI; a warning appears on `GET /admin/dashboard`.

## Quick references (repository)

- **Environment variables example:** **`.env.example`** file in the root (template; copy to local `.env`).
- **Base MCP registry:** **`config_std/mcp_registry.yaml`** (template; synced to `config/`).
- **Agent profiles:** **`config_std/profiles/`** (template; synced to `config/profiles/`).
- **Curated skills:** **`config_std/skills/`** (template; synced to `config/skills/`).
- **Synchronization script:** **`scripts/sync_config.py`** (populates the `config/` folder ignored by Git).
- **Skill frontmatter migration script:** **`scripts/migrate_skills_frontmatter.py`**

## Conventions

- The `AION_*` prefixes indicate variables read from `os.environ` in Python code.
- Features marked as *roadmap* or *stub* are described in [Hermes](./learning/hermes-features.md).

The **README** in the root of the repository summarizes the repo, link to the site, and how to open the doc locally without duplicating this map.

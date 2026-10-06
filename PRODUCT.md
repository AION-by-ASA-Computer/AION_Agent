# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Enterprise teams, technical leads, developers, and system administrators needing a self-hosted, sovereign AI agent platform. End users interact via the Chat UI for daily workflow execution and multi-step tasks; administrators manage profiles, skills, MCP servers, user permissions, and persistent memory via the Admin Panel.

## Product Purpose
AION Agent is a self-hosted, enterprise-grade platform for building and running sovereign AI agents. It gives organizations total control over their AI infrastructure, data, and models, eliminating third-party lock-in while providing advanced agentic capabilities (MCP tools, multi-level STM/LTM memory, dynamic skills, and Plan Mode).

## Positioning
Unlike SaaS AI assistants and hosted APIs, AION Agent is fully self-hosted, sovereign, and privacy-first, running on private infrastructure (on-prem or private cloud) with native Model Context Protocol (MCP) support, isolated multi-tenant execution, YAML profile customizability, and multi-tier memory (STM/LTM with SQLite FTS5 search).

## Operating Context
- **Chat UI (`chat-ui/`)**: Next.js 16 web interface for streaming chat, plan docks, file attachments, and interactive agent collaboration.
- **Admin UI (`admin-ui/`)**: Next.js 16 dashboard for managing profiles, skills, tools, users, and inspecting memory/databases.
- **Deployment**: Docker Compose / Caddy reverse proxy / standalone single-node setup with local LLMs (Ollama/vLLM) or external OpenAI-compatible endpoints.
- **Developer Workflow**: Monorepo with Python backend (`src/`), Next.js frontends (`pnpm`), and Docusaurus documentation (`website/`).

## Capabilities and Constraints
- **Agent Architecture**: FastAPI backend running Haystack Agent with single-worker constraints (`--workers 1`) due to in-process session caches and stdio MCP process pools.
- **Extensibility**: Modular skills (`src/skill_registry.py`), YAML profiles (`config_std/profiles/`), and persistent MCP stdio/SSE connections.
- **Memory & Storage**: Unified SQLite database (`data/aion.db`) with SQLAlchemy + Alembic, FTS5 full-text search, optional Redis cache, per-session sandboxes (`data/sessions/<session_id>/`).
- **Security & Auth**: Dual-layer authentication (HMAC-based Chat auth + independent Admin auth), credential encryption, organizational data isolation.

## Brand Commitments
- **Name**: AION Agent (by ASA Computer)
- **Design Philosophy**: High-density, professional, sovereign enterprise aesthetic with sleek dark/light theme support, low cognitive load, and clear status visibility for agent actions and tool calls.
- **Website & Documentation**: [https://aion-asa.com](https://aion-asa.com) and local docs site.

## Evidence on Hand
- Full source codebase with running backend and frontends.
- Complete documentation under `docs/` and `AGENTS.md` / `CLAUDE.md`.
- Reference screenshots under `assets/images/chat-ui.png` and `assets/images/admin-panel.png`.

## Product Principles
1. **Sovereignty & Privacy First**: No external telemetry or forced data sharing; organizations retain absolute ownership of memory, models, and sessions.
2. **Transparent Agency**: Tool calls, plans, and execution steps are visible, debuggable, and controllable in real time.
3. **Modular Extensibility**: Capabilities grow seamlessly via MCP servers, skills, and YAML profiles without core engine rewrites.
4. **Resilient Simplicity**: Single SQLite DB + optional Redis with graceful degradation; robust containerized deployment with Caddy.
5. **High-Signal Craft**: Interfaces prioritize density, clarity, and responsive feedback over generic chat bubbles.

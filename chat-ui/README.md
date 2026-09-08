# AION Agent — Chat UI

Next.js frontend client for the AION AI Agent.

## Overview

- **Framework**: Next.js 16 (App Router) + React 19 + TailwindCSS v4
- **Port**: 8003 (default dev server port)
- **Package Manager**: `pnpm` (workspace package)

## Getting Started

Run the development server from the `chat-ui` directory or workspace root:

```bash
# From chat-ui directory
pnpm dev

# Or from workspace root
pnpm --filter chat-ui dev
```

Open [http://localhost:8003](http://localhost:8003) with your browser.

## Environment & Backend Connection

- Backend API target is configured via `AION_API_HOST` / `AION_API_PORT` (default backend port: 8001).
- Environment variables are loaded automatically from the workspace root `.env` file via `next.config.ts`.

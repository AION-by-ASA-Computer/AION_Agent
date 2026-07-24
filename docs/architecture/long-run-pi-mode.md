---
title: Long Run mode (Pi backend)
sidebar_position: 13
description: Agent mode long_run using Pi worker, MCP bridge, and relaxed turn budgets.
---

# Long Run mode (Pi backend)

`long_run` is an agent mode for **multi-step deliverables** (web research + Excel/CSV in sandbox) using the [Pi](https://github.com/earendil-works/pi) agent loop instead of Haystack.

## Architecture

- **chat-ui** sends `agent_mode=long_run` on `POST /v1/chat/stream`
- **FastAPI** branches in `AgentPipeline` to `src/runtime/pi_runtime/pi_turn_runner.py`
- **Pi worker** (`services/pi-long-run/`) runs `createAgentSession()` with AION tools via HTTP bridge
- **MCP** stays in Python: `POST /internal/pi/tools/invoke` → `mcp_manager.call_tool_pooled`
- **SSE** contract unchanged (`token`, `reasoning`, `tool_event`, `context_compacting`, `done`)

## Enable locally

```bash
# .env
AION_LONG_RUN_ENABLED=1
AION_PI_WORKER_URL=http://127.0.0.1:8791
AION_PI_WORKER_SECRET=dev-secret   # same on worker + backend

# Terminal 1
cd services/pi-long-run && npm install && npm run dev

# Terminal 2
uvicorn src.api.main:app --reload --reload-exclude data/sessions
```

Select **Long run** in the chat composer mode chip.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `AION_LONG_RUN_ENABLED` | `0` | Feature gate |
| `AION_PI_WORKER_URL` | `http://127.0.0.1:8791` | Worker HTTP base |
| `AION_PI_WORKER_SECRET` | empty | Shared secret (worker + backend) |
| `AION_LONG_RUN_TURN_TIMEOUT` | `3600` | Whole-turn timeout (seconds) |
| `AION_LONG_RUN_TOOL_CALLS_MAX` | `200` | Tool call cap |
| `AION_LONG_RUN_NO_PROGRESS_TIMEOUT_SEC` | `600` | Stall detector |

Session files: `data/sessions/<id>/.pi/` (`SYSTEM.md`, `skills/`, `models.json`, `tool_manifest.json`).

## Docker

Production `docker-compose.yml` includes optional `pi-worker` service. Set `AION_LONG_RUN_ENABLED=1` on `backend`.

## Related

- Harness v2 patterns (Haystack): [aion-harness-v2.md](./aion-harness-v2.md)
- Context compaction (Haystack mid-turn): [context-compaction.md](../memory/context-compaction.md)

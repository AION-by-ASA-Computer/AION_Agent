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
| `AION_TOOL_OFFLOAD_ENABLED` | `0` | Offload large tool results to `derived/tool_results/` |
| `AION_TOOL_LEDGER_ENABLED` | `0` | Inject per-session tool trace table |
| `AION_PI_CUSTOM_COMPACTION` | `0` | Pi compaction summary via AION backend |

See [context-offloading.md](./context-offloading.md) for the full flag list and rollout steps.

Session files: `data/sessions/<id>/.pi/` (`SYSTEM.md`, `skills/`, `models.json`, `tool_manifest.json`).

## Docker

Production `docker-compose.yml` includes optional `pi-worker` service. Set `AION_LONG_RUN_ENABLED=1` on `backend`.

## Pi-native compaction

Pi maintains its own session transcript and runs **compaction inside the worker** when context nears the model window (`settings.json` → `compaction.reserveTokens` / `keepRecentTokens`, env `AION_PI_COMPACTION_*`).

- Events: `compaction_start` / `compaction_end` → SSE `context_compacting { active: true|false }`
- The worker may **pause token streaming** during compaction (no bug in chat-ui); the turn continues after `compaction_end`
- chat-ui shows the banner **above the composer** (always visible while scrolling)
- Do **not** stop the turn manually unless it exceeds `AION_LONG_RUN_TURN_TIMEOUT`; compaction can take 10–60s on large sessions

Haystack mid-turn compaction (normal mode) is documented in [context-compaction.md](../memory/context-compaction.md).

## Related

- Harness v2 patterns (Haystack): [aion-harness-v2.md](./aion-harness-v2.md)
- Context compaction (Haystack mid-turn): [context-compaction.md](../memory/context-compaction.md)
- Context offloading (tool result microfiles + ledger): [context-offloading.md](./context-offloading.md)

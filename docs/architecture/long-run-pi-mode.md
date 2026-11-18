---
title: Long Run mode & native consolidation
sidebar_position: 13
description: "Consolidation of Long Run mode: transition from the architecture with the external Pi Agent worker to unified native execution in AION."
---

# Long Run Mode & Native Consolidation

:::info Design note
Historical note on how long-running, multi-step execution moved from an external Node.js worker into the native AION runtime. Status: implemented — the external worker has been removed and the listed modules exist under `src/runtime/` and `src/memory/`.
:::

:::note
**Consolidation completed**: the execution mode for long, multi-step tasks is now **fully handled by the native AION runtime** (Harness V2 / Haystack).

The external Node.js worker (`services/pi-long-run`) has been retired in favour of a unified Python architecture that offers better performance, lower latency and built-in persistence.
:::

---

## Unified architecture

All the requirements for complex, long-running sessions are built into the native backend:

- **In-process execution:** no extra network round-trips to intermediate Node.js processes.
- **Context offloading (L1):** large tool outputs are automatically saved to files (`src/runtime/tool_offload.py`).
- **Tool ledger (L2):** a concise history of actions injected into the context (`src/runtime/tool_ledger.py`).
- **Circuit breaker:** native anti-loop protection against repeated errors (`src/runtime/tool_circuit.py`).
- **Dynamic compaction:** automatic context summarization that preserves cut points (`src/memory/context_compressor.py`).

---

## Related documents

- [Technical assessment and consolidation](./aion-vs-longrun-assessment.md)
- [AION Harness v2](./aion-harness-v2.md)
- [Context Compaction](../memory/context-compaction.md)
- [Context Offloading](./context-offloading.md)

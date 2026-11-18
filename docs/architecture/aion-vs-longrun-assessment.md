---
title: Native AION vs Long-Run Mode (Pi Agent) — Assessment and Consolidation
sidebar_position: 20
description: "Technical analysis and report on the architectural consolidation: retirement of the external Pi Agent worker and full native integration into AION (Haystack runtime)."
---

# Native AION vs Long-Run Mode (Pi Agent) — Assessment and Consolidation

:::info Design note
Technical assessment comparing the native AION runtime with the former external Pi Agent worker, and the resulting consolidation decision. Status: implemented — the Pi worker is gone and offloading, ledger, circuit breaker and compaction live in `src/runtime/` and `src/memory/`.
:::

:::note
**Architectural status (completed)**: the technical assessment led to the **complete retirement of the external Node.js worker (Pi Agent)** and to the integration of all the robustness patterns (L1 tool offloading, L2 tool ledger, circuit breaker, native compaction) directly into AION's native Python runtime (Haystack).

The AION backend is now unified in a single, fast, reliable process with no external closed dependencies.
:::

---

## 1. Consolidation executive summary

| Dimension | Old approach (Pi Long-Run Worker) | Current state (integrated native AION) |
|---|---|---|
| **Architecture** | ❌ Separate Node.js service (`services/pi-long-run`) with external dependencies | ✅ **Single in-process Python/Haystack process** |
| **Speed & latency** | ❌ Overhead of 2+ HTTP/NDJSON network hops for every single tool call | ✅ **High-performance in-process execution** with real parallelism (`ToolInvoker` / `ThreadPoolExecutor`) |
| **Persistence & memory** | ❌ In-memory-only sessions on the Node side (risk of data loss) | ✅ **Unified SQLite persistence** with full-text search (FTS5) and LTM/STM memory management |
| **Tool offloading (L1)** | ⚠️ Partial and mediated by internal HTTP calls | ✅ **Native (`src/runtime/tool_offload.py`)** with storage on file and previews in the prompt |
| **Tool ledger (L2)** | ⚠️ Asynchronous hook towards the backend | ✅ **Native (`src/runtime/tool_ledger.py`)** with JSONL tracking and injection into the context |
| **Circuit breaker** | ⚠️ Implemented only in the external worker | ✅ **Native (`src/runtime/tool_circuit.py`)** against loops of repeated failures (`AION_TOOL_CIRCUIT_BREAKER_MAX`) |
| **Compaction** | ⚠️ Opaque fallback over the HTTP bridge | ✅ **Native (`src/memory/context_compressor.py`)** with consistent cut points (`AION_HARNESS_V2_COMPACTION`) |

---

## 2. Architectural decision and rationale

The comparative assessment of the source code highlighted two key factors that drove the migration:

1. **The speed gap was structural:**
   The external Pi worker required every call and result to be serialized over an HTTP/NDJSON bridge between Python and Node.js. This added unavoidable latency to every interaction with the tools.

2. **Pi's strengths were purely logical and portable:**
   Features such as the *tool ledger*, *tool result offloading*, the anti-loop *circuit breaker* and context protection did not require a separate Node runtime; they could be implemented more robustly and efficiently directly inside the AION pipeline.

---

## 3. Features integrated natively into AION

### 3.1 Tool result offloading (`L1`)
- **Module:** [`src/runtime/tool_offload.py`](../../src/runtime/tool_offload.py)
- **How it works:** tool results that exceed the character threshold (`AION_TOOL_OFFLOAD_MIN_CHARS`, default 8000) are automatically written to disk in `data/sessions/<session_id>/derived/tool_results/`.
- **In the model context:** a targeted preview with the file path remains, drastically reducing token consumption without losing information.

### 3.2 In-session tool ledger (`L2`)
- **Module:** [`src/runtime/tool_ledger.py`](../../src/runtime/tool_ledger.py)
- **How it works:** keeps a compact, chronological JSONL log of all the tools invoked in the session.
- **Context injection:** a structured table is automatically injected into the agent prompt, letting the model keep track of progress even across successive compactions.

### 3.3 Tool circuit breaker
- **Module:** [`src/runtime/tool_circuit.py`](../../src/runtime/tool_circuit.py)
- **How it works:** intercepts and blocks repeated attempts to call the same tool with failing parameters (e.g. truncated parameters or wrong paths), preventing infinite loops and wasted token budget.
- **Configuration:** controlled by `AION_TOOL_CIRCUIT_BREAKER_MAX` and `AION_TOOL_CIRCUIT_BREAKER_ENABLED`.

### 3.4 Advanced context compaction (Harness V2)
- **Modules:** [`src/memory/context_compressor.py`](../../src/memory/context_compressor.py) and [`src/runtime/turn_compaction.py`](../../src/runtime/turn_compaction.py)
- **How it works:** when the context approaches the model's maximum limit, the oldest history is summarized while preserving valid cut points (it never splits tool call / tool response pairs) and is combined with the ledger of the tools that were executed.
- **Control:** enabled with `AION_HARNESS_V2_COMPACTION=1`.

---

## 4. Benefits of the consolidation

- **Zero external closed-source dependencies:** the npm package `@earendil-works/pi-coding-agent` has been removed.
- **Operational simplification:** no additional Node.js process or container to start, monitor or authenticate with shared keys.
- **Greater responsiveness:** native, real-time end-to-end SSE streaming from the FastAPI server to the web client.
- **Resilience and persistence:** all conversations, memories and offloads are persisted in the unified SQLite database and in the local session file system.

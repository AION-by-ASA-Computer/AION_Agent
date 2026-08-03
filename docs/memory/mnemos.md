---
sidebar_position: 2
title: Mnemos Long-Term Memory
description: Native LTM backend — notes, hierarchical digests, wake/recall, project scope.
---

# Mnemos (LTM v2)

AION Mnemos replaces the external MemPalace MCP server with an **in-process** long-term memory backend on the unified SQLite database (`data/aion.db`).

## Concepts

| Concept | Description |
|---------|-------------|
| **Note** | Single-line durable fact (≤500 chars), append-only per scope (`seq` assigned server-side) |
| **Digest** | LLM-compressed summary over a block of notes (hierarchical) |
| **Scope** | `(tenant_id, scope_type, scope_key)` — `user`, `project`, or `global` |
| **Project** | Hybrid entity: same `projects` row binds **SQL QueryMemory** and **Mnemos** notes |

## Agent tools (native)

| Tool | Purpose |
|------|---------|
| `memory_recall` | FTS search; `mode=current\|historical` |
| `memory_note` | Explicit “remember now” |
| `memory_forget` | User-requested correction |

`memory_wake` runs **server-side** at turn start (injected in user prefix).

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `AION_LTM_WAKE_MAX_ROWS` | `20` | Wake budget k |
| `AION_MNEMOS_RECALL_LIMIT` | `10` | Recall top-N |
| `AION_LTM_MIN_IMPORTANCE` | `2` | Post-turn extraction filter |
| `AION_MNEMOS_NATIVE_TOOLS` | `1` | Enable native memory tools |

## REST (chat-ui)

- `GET /v1/project-memory/notes` — list project notes
- `POST /v1/project-memory/notes` — create note
- Admin: `/admin/ltm/*` — browse, compress, zoom

## Skills

- `ltm_note_extraction` — post-turn JSON extractor (internal)
- `memory_protocol` — agent protocol
- `ltm_digest_compression` — digest job (internal)

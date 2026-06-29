---
name: mempalace_protocol
description: MemPalace wings, LTM auto-save, and when to use KG vs drawers (non-datasource profiles).
tags: [memory, ltm, mempalace]
status: verified
source: curated
version: 4
---

# MemPalace Protocol

## Relational datasource assistants

If the profile has **SQL QueryMemory** + **mempalace** MCP (e.g. Postgres/MySQL metadata assistants), follow **`datasource_memory_protocol`** for the full two-layer flow (QueryMemory + `wing_proj_{project}` navigation).

## How memory is saved in AION

| MemPalace / OpenClaw | AION |
|----------------------|------|
| Stop hook → save after work | Post-turn `ltm_orchestrator.extract_and_persist` |
| PreCompact | `precompact_flush` before STM compression |
| Wake-up | Injected in turn header |
| Agent writes during chat | You call MCP when user asks to remember **now** or after a verified lesson |

No server-side regex on «ricorda» / «memorizza».

## Tools

- **`mempalace_search`** — NL retrieval over drawers.
- **`mempalace_kg_query`** — structured relationships.
- **`mempalace_kg_add`** — atomic facts (relations, preferences).
- **`mempalace_add_drawer`** — short verbatim lessons (not full SQL).
- **`mempalace_check_duplicate`** — before new navigation facts.

For DB navigation on project wings, **do not** pass `wing` — chat-ui sets `wing_proj_{slug}`.

## Wings

| Pattern | Purpose |
|---------|---------|
| `wing_proj_{slug}` | DB navigation for active SQL project |
| `wing_user_{id}` | Personal preferences |
| `wing_aion_system` | Company facts + KG |
| `wing_session_context` | Recurring session context |

## Remember now

1. Same turn: `mempalace_kg_add` (+ optional short drawer on `wing_user_*` / `wing_aion_system`).
2. Max 1–2 write tools, one-sentence confirmation.
3. Post-turn LTM may also persist — avoid huge duplicate drawers.

## What NOT to store

Full SELECT text (QueryMemory), MCP transport errors, catalog dumps, company facts in `wing_proj_*`.

---
name: datasource_memory_protocol
description: Two-layer memory for SQL datasource assistants — QueryMemory SQL + Mnemos notes on the same project.
tags: [memory, sql, mnemos, navigation, datasource]
status: verified
source: curated
version: 5
---

# Datasource Memory Protocol

SQL metadata profiles use **two layers on the same project slug**:

| Layer | Tools | Stores |
|-------|-------|--------|
| **SQL QueryMemory** | `sql_memory_search`, `sql_memory_save`, … | Validated SELECT templates |
| **Mnemos LTM** | `memory_recall`, `memory_note` | Navigation lessons, pitfalls, decisions |

## Read path

1. `sql_memory_search` for reusable SQL on the active project.
2. `memory_recall` for navigation context (JOIN paths, pitfalls, conventions).
3. Run SQL via toolbox; verify results.

## Write path (after verified success)

| What | Tool | Category hint |
|------|------|----------------|
| Reusable SELECT | `sql_memory_save` | — |
| JOIN path / entry point | `memory_note` | `join_paths` → use `pitfall` or `fact` |
| Failed attempt | `memory_note` | `pitfall` |
| Schema convention | `memory_note` | `heuristics` → use `fact` or `decision` |

Do **not** duplicate full SQL text in Mnemos when QueryMemory already holds it.

## Scope

- Project lessons → `scope=project` (automatic when a project is active).
- Personal prefs → `scope=user`.
- Org-wide facts → `scope=global` (rare).

## Remember now

When the user says "ricorda / memorizza", call `memory_note` in the same turn (importance ≥ 4).

See also `memory_protocol` and `sql_query_memory_protocol`.

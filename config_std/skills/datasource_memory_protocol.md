---
name: datasource_memory_protocol
description: SQL QueryMemory + MemPalace navigation for relational datasource assistants (any engine).
tags: [memory, sql, mempalace, navigation, datasource]
status: verified
source: curated
version: 2
---

# Datasource memory (SQL + navigation)

**Scope:** assistants that query a **relational database** via a toolbox MCP (`toolbox-postgres`, `toolbox-mysql`, …) and optional catalog MCP (e.g. OpenMetadata). Same **project slug** in chat-ui for both memory layers.

There is **no** hardcoded schema map in the repo. You **discover** tables, columns, and JOIN paths by exploration, then **persist** what you learn so the next turn reuses it.

## Two layers (same project)

| Layer | Tools | Stores |
|-------|--------|--------|
| **SQL QueryMemory** | `sql_memory_*`, `search_known_sql`, `save_successful_sql` | Validated **SELECT** text (NL → SQL) per project |
| **MemPalace navigation** | `mempalace_search`, `mempalace_list_drawers`, `mempalace_add_drawer`, `mempalace_kg_*` | **Why/how** to navigate tables (JOIN paths, entry points, pitfalls) in `wing_proj_{slug}` |

**Do not** duplicate full SQL in MemPalace when QueryMemory already has the query. **Do not** use PromQL memory tools (`search_known_query`, `save_successful_query`) for SQL.

## Project and wing (chat-ui)

- Active project = `sql_query_project` from chat-ui → `wing_proj_{slug}` for MemPalace (runtime **injects** wing — **do not** pass `wing` on MemPalace tools).
- **Project is fixed per turn:** the agent **cannot** pass `project` on SQL memory tools or switch/list other QueryMemory drawers. Server enforces the chat-ui selection and user membership.
- Read constraints from the **`[project_context]`** block (project description from DB): preferred schema, dialect, read-only rules, business scope.
- Company-wide facts → `mempalace_kg_add` + `wing_aion_system` or `wing_user_*`, **not** `wing_proj_*`.

## Mandatory flow: search → explore → ask → execute → persist → answer

This matches the runtime **DATASOURCE MEMORY WORKFLOW** injected on SQL metadata profiles (`src/runtime/datasource_memory_mode.py`).

### 1. Search memory (always first)

Unless the turn header includes **QueryMemory — server cache** (see below):

1. `sql_memory_search` / `search_known_sql` for the active project.
2. `mempalace_search` with the user's intent (wing is automatic).

If both return strong matches → adapt and execute; skip broad exploration.

If `no_relevant_memory: true` or weak similarity → proceed to exploration.

### 2. Explore (when memory is empty or weak)

- Read **project description** for schema/database constraints before calling tools.
- Use **targeted** `list_tables`: pass `schema_name` when the project description names one; avoid dumping every schema on the server.
- Introspect candidates: `list_tables` with `table_names=[...]` on likely tables only.
- Build JOIN hypotheses from FK metadata, column names (`user_id`, `device_id`, `to_user_id`, …), and sample queries.
- Prefer one focused path over scanning unrelated schemas.

### 3. Ask the user (mandatory when stuck)

Ask **before** guessing if:

- Multiple schemas are plausible and the project description does not constrain one.
- A column's business meaning is not deducible from metadata or samples.
- Zero rows and filters are ambiguous (name spelling, status, date range).
- No obvious join key between two tables.

Ask **1–2 concise questions** in the user's language. Do not loop silently.

### 4. Execute

- Read-only **SELECT** only (unless the profile explicitly allows writes).
- Dialect-safe SQL: verify column names from introspection; escape apostrophes in string literals (`''` in SQL).

### 5. Persist BEFORE the final answer (mandatory when you explored or verified a new path)

**Do not** send the final answer to the user until persistence succeeds when this turn involved new exploration or a newly verified SQL path:

| What | Tool | MemPalace room |
|------|------|----------------|
| Reusable business SQL | `sql_memory_save` / `save_successful_sql` (`is_verified=true`) | QueryMemory |
| Fix obsolete saved SQL | `sql_memory_update` / `update_sql_memory_entry` by id, or `sql_memory_delete` | QueryMemory |
| Table path + **JOIN keys + columns used** | `mempalace_add_drawer` | `join_paths` or `entry_points` |
| Failed attempt worth remembering | `mempalace_add_drawer` | `pitfalls` |
| Schema/filter conventions | `mempalace_add_drawer` | `heuristics` |
| Stable relation (optional) | `mempalace_kg_add` | KG |

Before `mempalace_add_drawer`, call `mempalace_check_duplicate` when unsure.

**Drawer format (you write it, English, ≤500 chars, one lesson per drawer):**

```
Q: device assigned to user by name (iPhone)
Schema: example_schema
Entry: Users (nome, cognome, user_id, prid)
Path: Users.user_id = DeviceMovement.to_user_id; latest row by movement_date DESC; Device.device_id; filter Device.type='iPhone'
Pitfall: use nome/cognome not first_name; escape apostrophe in D''Agostaro
```

Include **schema**, **tables**, **join keys**, **columns**, and **pitfalls** — not generic "verified path" one-liners.

### 6. Answer

Concise, data-backed reply in the user's language after persistence (when step 5 applied).

## Server cache (pre-turn inject — reuse only)

When the turn header includes **«QueryMemory — server cache»**, the backend found a **high-confidence** match from memory **you or a prior session saved**:

- Run `execute_sql` with the injected SQL first (adapt placeholders).
- `list_tables`, `sql_memory_search`, and `mempalace_search` may be **blocked** until SQL succeeds or exploration unlocks.
- Still call `sql_memory_save` / `mempalace_add_drawer` if you adapt the path materially.

## MemPalace rooms (`wing_proj_{project}`)

| Room | Use |
|------|-----|
| `entry_points` | Where to start (which table for the business question) |
| `join_paths` | Verified JOIN keys and order |
| `pitfalls` | Paths that fail or return 0 rows |
| `heuristics` | Filters, conventions, dialect quirks |
| `limitations` | Timeouts, huge tables, permissions |
| `discoveries` | Recent findings to classify later |

## When NOT to use MemPalace writes

- User only wants text in chat (“paste”, “read the map”) → search/list only; runtime may block writes on read-only doc turns.
- Catalog discovery belongs in **OpenMetadata** (or engine catalog tools) — do not dump raw catalog into MemPalace.

## Do not save

- Full SELECT text in MemPalace (QueryMemory only).
- Broad schema dumps (`information_schema` / `pg_catalog` / `SHOW TABLES` only) without a reusable lesson.
- Generic one-liners like "Percorso verificato per «Nome Cognome»" without schema, join keys, and columns.
- Every `list_tables` output — if nothing new was learned, skip MemPalace writes.
- Failed SQL without a reusable lesson.
- MCP transport errors — transient.
- Duplicate drawers (check first).

### Good vs bad drawer examples

**Good (`join_paths`):**
```
Q: device assigned to user by name (<DEVICE_TYPE>)
Schema: aion_assetmanager_2
Path: Users.user_id = DeviceMovement.to_user_id; latest movement_date; Device.device_id; filter type='<DEVICE_TYPE>'
Pitfall: nome/cognome columns; escape apostrophe in names
```

**Bad (do not save):**
```
Verified path for "What PC does Giuseppe La Rocca have": join across users, devicemovement, device.
```

## Answer delivery

- After tool results are sufficient, **write the final answer as assistant text** — do not plan the full reply only in thinking.
- Keep thinking short: plan → tools → persist → answer.
- Do not claim "not found" until you have tried ~3 join hypotheses or asked the user; save failed attempts in `pitfalls`.

## Remember now (explicit remember / memorize requests)

1. **Same turn:** `mempalace_kg_add` for atomic facts; optional short drawer on `wing_user_*` / `wing_aion_system` — max **2** write tools, then confirm.
2. **Post-turn:** AION runs LTM extraction automatically (`ltm_extraction`).

See also `mempalace_protocol` for wing taxonomy and non-SQL assistants.

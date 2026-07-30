---
name: wren
description: "Wren CLI for AI agents — semantic SQL layer over Postgres and 20+ databases. Discovery stub; full workflow guides live in `wren skills get`. Use on profiles with Wren enabled for analytical SQL. Triggers: data questions, top N, trends, wren usage, MDL, semantic SQL."
tags: [wren, sql, semantic-layer, postgres]
status: verified
source: curated
version: 2
---

# Wren CLI (AION)

Discovery stub — workflow guides ship inside the `wren` CLI (`wren skills get <name>`).
Load **`wren skills get usage`** before the first data question in a session.

**AION execution:** use `sandbox_exec_allowlisted` (not raw shell). The active Wren project is resolved from the profile (`wren_project_path`) and/or `AION_WREN_PROJECT_PATH` (injected as `WREN_PROJECT_HOME` at runtime).

**Schema discovery:** never guess model or column names. Run `wren context show` and `wren context instructions` for the bound project before writing SQL.

## Mandatory flow (data questions)

1. **SEARCH** — `sql_memory_search` + `mempalace_search` (AION QueryMemory + MemPalace).
2. **Context** — `sandbox_exec_allowlisted(["wren", "context", "show"], timeout_sec=60)`; on first turn in session also `["wren", "context", "instructions"]`.
3. **Recall** (optional) — `["wren", "memory", "recall", "-q", "<question>", "--limit", "3"]`.
4. **Execute** — SQL against **MDL model names** from `context show`, not raw database schema qualifiers (`public.*`, etc.):
   - `sandbox_exec_allowlisted(["wren", "--sql", "<SELECT ...>", "-o", "table"], timeout_sec=180)`
   - Complex JOINs: `["wren", "dry-plan", "--sql", "<SQL>"]` first.
5. **Persist** — `sql_memory_save` + `mempalace_add_drawer` when you verified a new reusable path.
6. **Answer** — concise, data-backed.

On Wren-enabled profiles, do **not** use raw toolbox SQL tools (`toolbox-postgres`, `execute_sql`, `list_tables`) unless the profile explicitly lists them.

## Workflow guides (via sandbox)

```text
["wren", "skills", "list"]
["wren", "skills", "get", "usage"]
["wren", "skills", "get", "generate-mdl"]
["wren", "skills", "get", "onboarding"]
```

Add `--full` to `skills get` for reference docs. Connection fields: `["wren", "docs", "connection-info", "<datasource>"]` (e.g. `postgres`).

## Day-to-day commands

| Task | argv |
|------|------|
| Query | `["wren", "--sql", "SELECT ...", "-o", "table"]` |
| Dry-plan | `["wren", "dry-plan", "--sql", "SELECT ..."]` |
| Models | `["wren", "context", "show"]` |
| Instructions | `["wren", "context", "instructions"]` |
| Profile debug | `["wren", "profile", "debug"]` |
| Validate MDL | `["wren", "context", "validate"]` |
| Build MDL | `["wren", "context", "build"]` |

## Error recovery

| Symptom | Fix |
|---------|-----|
| `exec_disabled` | Set `AION_FS_POLICY_PATH` to a policy with `exec.enabled: true` |
| `allowlist_denied` | `wren` must be on fs_policy exec allowlist |
| `table not found` | Re-run `context show`; use MDL model names from the bound project |
| `timeout` | Use `timeout_sec=180` or higher on heavy aggregations |

See also `datasource_memory_protocol` for MemPalace drawer format.

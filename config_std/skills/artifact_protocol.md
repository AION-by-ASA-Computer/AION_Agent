---
name: artifact_protocol
description: "Tool-first file delivery for AION (sandbox write/edit/patch tools)."
tags: [core, protocol, code]
status: verified
source: curated
version: 9
---

# Artifact Protocol

## Primary path: filesystem tools (OpenCode-style)

**Creating or updating files = call a registered sandbox tool.**

| Task | Tool |
|------|------|
| New file or full rewrite | `sandbox_write_workspace_file(relative_path, content)` |
| Small change on existing file | `sandbox_edit_workspace_file(relative_path, old_string, new_string)` |
| Multi-file / incremental (GPT) | `sandbox_apply_patch(patch_text)` |
| Run generated script | `sandbox_run_node_file` / `sandbox_run_python_file` |

| Do | Don't |
|----|-------|
| Write complete file bodies via tools | Dump full files in chat |
| `sandbox_install_npm_packages` **before** docx-js scripts | Install deps after a failed run |
| Read file section before edit | Call `sandbox_edit_workspace_file` with `{}` or missing `relative_path` |
| Retry with fixed arguments after tool error | Invent tools `aion_artifact`, `artifact`, `create_file` |

## Operational order (e.g. Word .docx)

1. `skill_search("docx")` → `skill_view("docx")` when available.
2. `sandbox_install_npm_packages(["docx"])` — if not already installed.
3. `sandbox_write_workspace_file` with a **complete** `workspace/create_doc.js` script.
4. `sandbox_run_node_file(relative_path="workspace/create_doc.js")`.

If `skill_search("docx")` returns nothing, **still proceed** with docx-js via write tool (see `core_protocol`).

## Data-heavy deliverables (web → workspace → output)

When the deliverable is built from **external data** (web search, fetch, APIs):

```
web_search / web_fetch_page  →  workspace/<slug>_data.csv|.json  →  sandbox_run_python_file  →  workspace/<output>.xlsx
```

1. **Early skeleton** — create `workspace/<slug>_data.*` with headers and first rows as soon as data exists.
2. **Incremental commits** — each research slice updates the data file before the next slice (see `incremental_execution_protocol`).
3. **Final artifact** — generate `.xlsx` / `.docx` via sandbox tools; do not paste tables in chat.
4. **Office skill** — `skill_view("xlsx")` (or docx/pdf) when you start **writing** the deliverable, not during initial web scout.

## Rules

1. One tool write per new file when possible. No duplicate writes.
2. File body must be **complete** (no `...` or “rest omitted”).
3. Reply to the user in their language (chat prose only — this skill stays English).

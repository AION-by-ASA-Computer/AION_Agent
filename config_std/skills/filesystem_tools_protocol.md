---
name: filesystem_tools_protocol
description: "Protocol for advanced session workspace navigation and editing (grep, glob, chunk read, edit)."
tags: [core, protocol, filesystem, coding]
status: verified
source: curated
version: 5
---

# Filesystem Tools Protocol

## When to use each filesystem tool

| Scenario | Recommended tool |
|----------|------------------|
| Create a new file | **`sandbox_write_workspace_file`** — read first if the file may already exist |
| Small targeted change on existing file | **`sandbox_edit_workspace_file`** — always `relative_path`, `old_string`, `new_string` (optional `replace_all`) |
| Multi-file or incremental patch (GPT) | **`sandbox_apply_patch`** |
| Find where a pattern appears | `sandbox_grep_content` |
| List files by wildcard/pattern | `sandbox_fnmatch_glob` |
| Read part of a large file | `sandbox_read_file_chunk` |
| Execute Python script | `sandbox_run_python_file` (`workspace/*.py` only) |
| Office skill helpers (unpack/pack) | `skill_view(docx)` then `sandbox_exec_allowlisted` on `scripts/office/...` |
| After docx unpack (read/grep/edit XML) | Unpack to **`workspace/unpacked/`**; then `sandbox_grep_content`, `sandbox_read_text_file`, `sandbox_edit_workspace_file` under `workspace/unpacked/` |
| Install npm packages (docx, …) | `sandbox_install_npm_packages` (not `sandbox_exec_allowlisted`) |
| Find orchestration plan for this chat | **`list_session_execution_plans`** — **never** `sandbox_fnmatch_glob("execution_plan_*.md")` |
| Execution plan progress / task list | **`get_execution_plan`** (plan_id optional) — **not** workspace files |
| Edit execution plan (goal, tasks, deps) | **`update_execution_plan`** — full markdown to DB |


## Workflow: multi-file refactor

```text
1. sandbox_fnmatch_glob("**/*.py") to list candidate files
2. sandbox_grep_content("old_pattern") to locate matches
3. For each file:
   a) sandbox_read_file_chunk(file) to confirm context
   b) sandbox_edit_workspace_file(file, old, new) to patch
4. sandbox_run_python_file to validate runtime behavior
```

## Workflow: large-file analysis

```text
1. sandbox_read_file_chunk(file, max_lines=50) for preview + total_lines
2. If truncated=true, continue with offset_lines
3. sandbox_grep_content(pattern, glob_filter="filename.ext") for precise search
```

## Tool preference order (OpenCode-style)

1. **`sandbox_edit_workspace_file`** — smallest change on an existing file
2. **`sandbox_apply_patch`** — multi-hunk / multi-file (when exposed for your model)
3. **`sandbox_write_workspace_file`** — new file or full rewrite only when edit/patch is impractical

## `sandbox_edit_workspace_file` — required parameters

The model must pass **all** of these fields in a single call:

```json
{
  "relative_path": "workspace/file_name.py",
  "old_string": "exact text to replace",
  "new_string": "new text"
}
```

Do not call the tool with only `old_string` / `replace_all`: `relative_path` is missing and the server rejects the request.

## Common error handling

**Edit `missing_arguments`**
- Re-read the file with `sandbox_read_file_chunk` and retry the call with all three required parameters.

**Edit `zero_matches`**
- Re-read the section with `sandbox_read_file_chunk`.
- Use `sandbox_grep_content(..., fixed_string=True)` to locate exact text.
- The file may have changed since the previous read.

**Run `file_not_found` / `empty_file`**
- Create the script with `sandbox_write_workspace_file` before `sandbox_run_node_file` or `sandbox_run_python_file`.

**Grep `invalid_regex`**
- Use `fixed_string=True` for literal matching.
- Or escape regex special characters.

**Grep `invalid_root` / empty glob after unpack**
- Unpack output must be under `workspace/unpacked/` (recommended) or use `relative_root="unpacked"` if you used session-root `unpacked/`.
- Do not pass `max_bytes` to `sandbox_grep_content` — use `max_file_bytes` (alias `max_bytes` is also accepted).

## Notes

- `pandoc` must be on PATH in the backend container/host; prefer unpack + sandbox grep/read for `.docx` edits.
- Paths are always relative to the session root; writable code lives under `workspace/`.

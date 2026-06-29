---
name: artifact_protocol_tool
description: "Protocol for code/file generation through dedicated filesystem tools."
tags: [core, protocol, code, tool]
status: verified
source: curated
version: 3
---

# Artifact Protocol (Tool JSON)

Use filesystem tools for file creation/updates. Do not paste long code directly in plain response text.

## Filesystem tools
- `sandbox_write_workspace_file(relative_path, content)` for new files or full rewrites. *(Note: Do NOT call this tool to manually write files if you are already outputting the file's content inside an XML or Markdown artifact block. The framework automatically parses and writes artifact blocks to the filesystem. Doing both is redundant and causes conflicts).*
- `sandbox_edit_workspace_file(relative_path, old_string, new_string)` for surgical edits.
- `sandbox_grep_content(...)` to locate code/text patterns.
- `sandbox_fnmatch_glob(...)` to discover files by wildcard.
- `sandbox_read_file_chunk(...)` to inspect large files safely.

## Recommended workflow
1. Discover (`glob`/`grep`).
2. Inspect (`read_file_chunk`).
3. Modify (`edit` or `write`).
4. Validate (`sandbox_run_python_file`) when relevant.

## Hard rules
1. Save HTML/presentation deliverables as `.html` files under `workspace/`.
2. Do not repeat the same write/edit action.
3. Prefer `edit` over full rewrite for small changes.
4. Keep internal reasoning concise; do not dump full payloads in `<thought>`.
5. Reply in the same language used by the user unless explicitly requested otherwise.

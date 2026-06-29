---
name: artifact_protocol_markdown
description: "Protocol for generating code/files with inline Markdown artifacts."
tags: [core, protocol, code, markdown]
status: verified
source: curated
version: 3
---

# Artifact Protocol (Markdown)

## Format

For Python code longer than 3 lines, generate a Markdown code block with metadata at the top:

```python
# artifact_id: data_analysis
# title: Data Analysis
# filename: analysis.py
import pandas as pd
df = pd.read_csv("uploads/data.csv")
print(df.describe())
```

## Rules

1. Metadata is mandatory:
   - `# artifact_id: unique_snake_case`
   - `# title: Human readable title`
   - `# filename: file.ext` (must be a pure basename, e.g. `analysis.py`. Do NOT prepend `workspace/`!)
2. Metadata must come before all code.
3. After artifact generation, call `sandbox_run_python_file(relative_path="workspace/<file>.py")` when execution is needed. (The actual file is saved under `workspace/` automatically).
4. Do not duplicate artifact generation.
5. For web pages/presentations, use `.html` artifacts (plus optional `.css`/`.js` assets). **Always** include `# artifact_id`, `# title`, and `# filename` before `<!DOCTYPE html>` — blocks without metadata render as plain chat code, not the artifact panel.
6. **NO DOUBLE WRITING**: Do NOT call `sandbox_write_workspace_file` to write the file manually if you are already using the Markdown artifact format. Emitting the Markdown block automatically saves the file to the workspace under `workspace/`. Doing both is highly redundant and causes conflicts.
7. **FILENAME PATHS**: Do NOT include the `workspace/` prefix in the `# filename:` metadata (e.g. use `filename: chart.py`, NOT `filename: workspace/chart.py`). The framework automatically prefixes `workspace/` when saving the artifact. Specifying `workspace/` results in saving the file to `workspace/workspace/chart.py`, which will fail subsequent execution.
8. Use filesystem helpers (`sandbox_grep_content`, `sandbox_fnmatch_glob`, `sandbox_read_file_chunk`) before editing large codebases.
9. For targeted changes, prefer `sandbox_edit_workspace_file`.
10. **SPECIALIZED SKILL LOAD**: Before creating artifacts for specialized file formats (e.g. Word `.docx`, Excel `.xlsx`, PowerPoint `.pptx`, PDF), you **MUST** call `skill_search` or `skill_view` on `skills_hub` to read and strictly follow the platform's standardized rules (e.g. the standard JS `docx` library with correct margins/shading for Word documents).
11. **NO RAW BYPASS**: Bypassing the Markdown code-block artifact system by writing code files directly via `sandbox_write_workspace_file` or CLI tools is strictly prohibited. Raw file-writing should be done *only* when outputting small surgical edits with `sandbox_edit_workspace_file`.
12. Reply to the user in the same language they used, unless they ask otherwise.

## Plan execution deliverables (markdown docs)

When executing an **approved orchestration plan** with a `## Deliverable` path (e.g. `workspace/report.md`):

1. **First write task** — create the file once (fenced artifact with `# filename:` **or** one `sandbox_write_workspace_file`).
2. **All later writing tasks** — **only** `sandbox_edit_workspace_file` on that path. Never emit a second full artifact or rewrite the entire file.
3. **Never** paste the full document in chat prose — the file in `workspace/` is the SSOT.
4. After finishing the current plan task, call `mark_task_completed` and **stop** (one task per agent turn).

## Anti-patterns (artifact will NOT be saved)

- **Missing `#` on metadata** — `artifact_id: foo` without `#` may fail unless the runtime salvage path recovers it; always use `# artifact_id:`.
- **Preamble before the fence** — do not write "Here is the document:" then the block; emit the fenced artifact directly.
- **Broken fences** — extra backticks (`filename: doc.md``````) truncate or corrupt the block.
- **Duplicate output** — never paste the full document in chat AND in an artifact; one fenced block only.
- **Multiple artifacts** for one deliverable — use a single block per file unless the user asked for multiple files.


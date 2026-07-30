---
name: artifact_protocol_xml
description: "Protocol for generating code/files with inline XML artifacts."
tags: [core, protocol, code, xml]
status: verified
source: curated
version: 3
---

# Artifact Protocol (XML)

## Plan Mode override

When the system prompt declares **PLAN MODE** active, **do not** emit `<aion_artifact>`, Python, or docx generation in that turn. Output only `<plan>...</plan>` per `core_protocol` / plan mode rules. Artifacts and file writes happen **after** plan approval.

## Format

```xml
<aion_artifact identifier="unique_name" type="python" title="Descriptive title" filename="script.py">
# your code here
</aion_artifact>
```

## Rules
1. Use artifacts for long code and structured files.
2. Use unique snake_case identifiers.
3. Always provide `filename` so output is saved under `workspace/`.
4. **NO DOUBLE WRITING**: Do NOT call `sandbox_write_workspace_file` to write the file manually if you are already using an `<aion_artifact>` block. Emitting the `<aion_artifact>` block automatically saves it in the workspace under `workspace/`. Doing both is highly redundant and causes conflicts.
5. **FILENAME PATHS**: Always specify the **basename** for the `filename` attribute without the `workspace/` prefix (e.g. `filename="chart.py"`, NOT `filename="workspace/chart.py"`). The framework automatically prefixes `workspace/` when saving the artifact. Including `workspace/` in the filename results in saving the file to `workspace/workspace/chart.py`, which will fail subsequent execution.
6. Use `auto_execute="true"` only for one-shot generation.
7. If execution is needed, call `sandbox_run_python_file` after artifact creation.
8. Do not generate duplicate artifacts for the same task.
9. Prefer `sandbox_edit_workspace_file` for small follow-up changes.
10. **SPECIALIZED SKILL LOAD**: Before creating artifacts for specialized file formats (e.g. Word `.docx`, Excel `.xlsx`, PowerPoint `.pptx`, PDF), you **MUST** call `skill_search` or `skill_view` on `skills_hub` to read and strictly follow the platform's standardized rules (e.g. the standard JS `docx` library with correct margins/shading for Word documents).
11. **NO RAW BYPASS**: Bypassing the `<aion_artifact>` system by writing code files directly via `sandbox_write_workspace_file` or CLI tools is strictly prohibited. Raw file-writing should be done *only* when outputting small surgical edits with `sandbox_edit_workspace_file`.
12. Keep reasoning concise and never place full artifact payloads inside `<thought>`.
13. Reply in the same language used by the user unless explicitly requested otherwise.


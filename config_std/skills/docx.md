---
name: docx
description: "Create and edit Word .docx files via docx-js in the session sandbox."
tags: [office, docx, word, document]
status: verified
source: curated
version: 2
---

# Word (.docx) via docx-js

## Workflow (tool-first)

1. `sandbox_install_npm_packages(["docx"])` if not already installed.
2. **`sandbox_write_workspace_file`** — write a complete `workspace/create_doc.js` script using the `docx` npm package.
3. **`sandbox_run_node_file(relative_path="workspace/create_doc.js")`** — generates the `.docx` under `workspace/`.

Do **not** use `<aion_artifact>` or phantom tools. Do **not** call `sandbox_run_node_file` before the script file exists.

## Minimal script shape

```javascript
const { Document, Packer, Paragraph, TextRun } = require("docx");
const fs = require("fs");
const path = require("path");

async function main() {
  const doc = new Document({
    sections: [{
      children: [new Paragraph({ children: [new TextRun("Title")] })],
    }],
  });
  const buf = await Packer.toBuffer(doc);
  const out = path.join("workspace", "output.docx");
  fs.writeFileSync(out, buf);
  console.log("Wrote", out);
}
main().catch((e) => { console.error(e); process.exit(1); });
```

## Editing existing docx

Prefer unpack/edit/pack workflows from office scripts when available via `skill_view` and `sandbox_exec_allowlisted` on materialized `scripts/office/...` paths.

## Errors

- **`empty_file` / `file_not_found` on run**: rewrite the script with `sandbox_write_workspace_file`.
- **Missing npm package**: run `sandbox_install_npm_packages` first.

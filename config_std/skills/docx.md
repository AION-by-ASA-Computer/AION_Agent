---
name: docx
description: "Create and edit Word .docx files via docx-js in the session sandbox."
tags: [office, docx, word, document]
status: verified
source: curated
version: 3
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

## Legacy `.doc` (Word 97–2003)

Binary `.doc` files **cannot** be read with `docx2txt`, `unpack.py`, or docx-js. On upload, the API host auto-converts them via **LibreOffice** (`soffice`) when `AION_OFFICE_AUTO_CONVERT_LEGACY_WORD=1` (default). Production Docker images ship `libreoffice-writer-nogui`; local dev needs LibreOffice on the API host (`brew install --cask libreoffice` on macOS).

- Check the attachments block for **`converted_docx_path`** (e.g. `derived/converted/report.docx`).
- Use **only that .docx path** for `skill_view("docx")`, unpack, and edits.
- Do **not** convert in the sandbox and do **not** call `unpack.py` on the original `.doc` binary.

If conversion is unavailable, install LibreOffice on the API server or set `AION_SOFFICE_PATH`.

## Evidence images (from PDF)

When building a report that cites PDF pages, use PNGs from `derived/docs/<slug>/evidence/`
produced by the MCP tool **`pdf_evidence_crop`** (server `ocr`). Do **not** run `pdftoppm`
full-page in the sandbox for evidence figures.

- Each figure needs a caption: `source_doc / section / pag. N`.
- Prefer `scripts/report/build_evidence_report.py` (after `skill_view("docx")`) when
  findings JSON + evidence PNGs are ready.
- Run `scripts/report/qa_evidence_images.py` on all evidence PNGs before delivery.

### Figure layout (critical for report quality)

When embedding PNGs with **python-docx**, never scale only by width — full-page crops become
~9″ tall and Word pushes them to the next page, leaving a white band under the section title.

Use `scripts/report/evidence_layout.py`:

- **Max width** 6.0″ (content column), **max height** 4.75″ — preserves aspect ratio.
- Put the **caption below** the image, not above.
- Do **not** insert a blank paragraph before the picture.
- Set **`keep_with_next`** on the heading / intro paragraphs so title and figure stay together.

`build_evidence_report.py` applies these rules automatically.

## Errors

- **`empty_file` / `file_not_found` on run**: rewrite the script with `sandbox_write_workspace_file`.
- **Missing npm package**: run `sandbox_install_npm_packages` first.

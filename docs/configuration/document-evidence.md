---
sidebar_position: 7
title: PDF evidence images for Word reports
description: MCP pdf_evidence_crop, QA gate, and report template for high-quality Word deliverables with PDF screenshots.
---

# PDF evidence images for Word reports

## Problem

Agents often embed **full-page PDF screenshots** (`pdftoppm`, `convert_pdf_to_images.py`) in Word
reports. The result looks unprofessional compared to targeted crops with captions and document
chrome (headers, scadenziario, figure appendix).

The fix is **orchestration**, not a different LLM: deterministic crop via MCP, protocol rules,
and optional proprietary report scripts.

```mermaid
flowchart LR
  PDF[uploads PDF] --> Ingest[doc_ingest]
  Ingest --> Grep[sandbox_grep]
  Grep --> Crop[pdf_evidence_crop]
  Crop --> PNG[derived/docs/slug/evidence]
  PNG --> Docx[build_evidence_report]
  Docx --> QA[qa_evidence_images]
  QA --> Out[workspace report.docx]
```

---

## MCP tool: `pdf_evidence_crop`

Server: **`ocr`** (`mcp_servers/ocr_mcp/`). Requires `AION_CHAT_SESSION_ID` (session-scoped pool).

| Argument | Description |
|----------|-------------|
| `relative_path` | Session path to PDF (e.g. `uploads/decreto.pdf`) |
| `page` | 1-based page number |
| `bbox` | Optional clip `{x0, y0, x1, y1}` in PDF points |
| `full_page` | When true and no bbox, skip auto-trim (still subject to white-ratio guard) |
| `dpi` | Render resolution (default `AION_PDF_EVIDENCE_DPI`, usually 200) |
| `caption` | Required caption for the figure |

**Output:** `derived/docs/<slug>/evidence/eNNN.png` + `eNNN.json` sidecar with `page`, `bbox`,
`white_ratio`, `cropped`, `caption`, `source_path`.

**Guard:** if `white_ratio` exceeds `AION_PDF_EVIDENCE_MAX_WHITE_RATIO` (default `0.90`), returns
`ok: false` / `too_much_whitespace` so the agent cannot ship a blank full-page dump. Pages with
a text layer are auto-cropped to text blocks first; sparse but real content pages get a slightly
higher ceiling than blank scans.

Implementation: `src/tools/pdf_evidence.py` (PyMuPDF render + Pillow auto-trim).

---

## Agent protocol

See skill **`long_document_protocol`** (no new slug):

1. After grep + read hits, call `pdf_evidence_crop` for each cited page.
2. Never use full-page `pdftoppm` for evidence figures.
3. Build Word from `workspace/<slug>_findings.json` + evidence PNGs.
4. Run QA before delivery.

Skill **`docx`** documents embedding PNGs from `derived/.../evidence/`.

---

## Proprietary report scripts (optional)

After `skill_view("docx")`, when proprietary config is synced:

| Script | Purpose |
|--------|---------|
| `scripts/report/build_evidence_report.py` | Structured report: cover, quadro obblighi, scadenziario, prescrizioni **with inline capped figures**, figure appendix |
| `scripts/report/qa_evidence_images.py` | Fail on high white-ratio, full-page aspect, or natural display height ≥6.5″ |
| `scripts/report/evidence_layout.py` | Shared max-width/max-height picture sizing for python-docx |

If proprietary packages are absent, MCP + OSS protocol still apply; template scripts are best-effort.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AION_PDF_EVIDENCE_DPI` | `200` | Default render DPI for `pdf_evidence_crop` |
| `AION_PDF_EVIDENCE_MAX_WHITE_RATIO` | `0.90` | Reject crops above this white pixel ratio |

---

## Eval

CI smoke: `evals/document_evidence/cases/smoke.yaml` — synthetic PDF crop + sidecar checks
(`python -m pytest src/test/test_document_evidence_eval.py -v`).

---

## Related

- [Office files and legacy Word](./office-and-legacy-word.md) — `.doc` conversion on upload
- [Skills and system prompt](./skills-and-prompts.md) — `long_document_protocol`, `docx`
- [MCP registry](../mcp/registry.md) — `ocr` server tools

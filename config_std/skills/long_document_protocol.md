---
name: long_document_protocol
description: "Mandatory protocol for finding and extracting facts from PDFs longer than a few pages: doc_ingest into one file per page, document identity check, exhaustive grep, verbatim citations with page numbers."
tags: [core, protocol, documents, pdf, ocr, extraction]
status: verified
source: curated
version: 4
---

# Long Document Protocol

## When this applies

Any request of the form "find / extract / summarize X from this document" where the
source is a PDF or scan of **more than ~10 pages**. Typical cases: decrees,
authorizations, contracts, technical reports, regulations.

If the document is short, or you only need to read it front to back, this protocol is
optional. Everything else below is mandatory.

## Never do these

| Shortcut | Why it fails |
|----------|--------------|
| `ocr_file` on a whole multi-page PDF | One vision-model call per page. On a 200-page file it always exceeds the MCP timeout, and the run is lost. |
| A custom `pypdf`/`pdfplumber` script that accumulates text in a variable | Killed by the OOM killer (exit code `-9`) on large files. |
| Concatenating everything into one big `.txt` and grepping it | `sandbox_grep_content` **silently skips** files above `AION_GREP_MAX_FILE_BYTES` (500 KB). You get zero hits and conclude, wrongly, that the term is absent. |
| Answering after the first few grep hits | Prescriptions and clauses repeat across chapters. Partial retrieval reads as a complete answer and is worse than no answer. |

## Step 1 — Verify extraction (auto-ingest on upload)

PDF uploads are **automatically extracted** to `derived/docs/<slug>/pages/pNNNN.txt`
(text layer only). Check the attachments block for `PDF extraction ready` or read
`derived/docs/<slug>/manifest.json`.

Call `doc_ingest(relative_path="uploads/<file>.pdf")` **only if**:
- manifest is missing (extraction still running),
- `"partial": true` (resume with `first_page=<resume_from>`),
- `empty_pages` need OCR (`ocr_mode="auto"`),
- or the user re-uploaded with `force=True`.

Never call `ocr_file` on the whole PDF. Never write custom extraction scripts.

Leave `write_full` off. A `full.txt` is exactly the file grep would skip.

## Step 2 — Identity gate (do not skip)

Read `title_guess` and `first_page_excerpt` from the manifest and confirm the document
is the one the user is asking about — the right plant, company, year, protocol number.

**If it does not match, stop and tell the user.** Do not proceed, do not name the
deliverable after what the user asked for. Producing a well-formatted report from the
wrong source document is the single most damaging failure mode in this workflow,
because nothing in the output looks wrong.

Also check `ocr_failed_pages` and `empty_pages`: those pages contain no usable text and
any conclusion of the form "the document does not mention X" is unsound while they
remain unread.

## Step 3 — Search

```
sandbox_grep_content(
    pattern="<regex>",
    relative_root="derived",
    glob_filter="docs/<slug>/pages/*.txt",
    max_matches=200,
)
```

The file name of each grep hit **is** the page number: `pages/p0101.txt` → page 101.

Widen the pattern before you run it. One spelling is never enough:

* case and accents: `[Rr]umor|[Aa]custic|acùstic`
* morphological variants: `rumor(e|osità)|acustic(o|a|he|i)|sonor`
* the domain synonyms a drafter would use: `dB\(A\)|Leq|fonometr|immission|emission`
* numbered markers, if the document uses them: `\[[0-9]{1,3}\]`

If a search returns `truncated: true`, narrow the glob to a page range and repeat —
do not accept a truncated result set as complete.

## Step 4 — Read every hit, plus one page either side

For each distinct page in the hit list:

```
sandbox_read_file_chunk(relative_path="derived/docs/<slug>/pages/p0101.txt")
```

Always read `page-1` and `page+1` as well. Clauses run across page breaks: a
prescription that starts at the bottom of one page and ends on the next is silently
truncated if you only read the page that matched.

## Step 4b — Evidence images (mandatory for Word deliverables)

For every finding that will appear in a report with a screenshot, call:

```
pdf_evidence_crop(
    relative_path="uploads/<file>.pdf",
    page=<page>,
    caption="<source_doc> / <section> / pag. <page>",
)
```

Rules:

| Rule | Why |
|------|-----|
| Use `pdf_evidence_crop`, not `pdftoppm` full-page | Full-page dumps fail the white-ratio guard and look unprofessional in Word. |
| Caption is mandatory | Every figure in the deliverable must cite doc / section / PDF page. |
| Read the sidecar JSON | `derived/docs/<slug>/evidence/eNNN.json` carries `white_ratio`, `bbox`, `cropped`. |
| If `ok: false` with `too_much_whitespace` | Tighten with an explicit `bbox`, or call `sandbox_list_files(subdir="uploads")` if the PDF path was wrong — do not attach the image. |

PNG output lives under `derived/docs/<slug>/evidence/eNNN.png`. Reference those paths in the
`docx` deliverable (or `scripts/report/build_evidence_report.py` when available).

## Step 5 — Record findings as you go

Append to `workspace/<slug>_findings.json`, one object per extracted item, never in
your reasoning only:

```json
{
  "id": "53",
  "source_doc": "<slug>",
  "page": 101,
  "section": "8.9 Rumore",
  "verbatim_quote": "Il Gestore è tenuto al rispetto dei valori limite...",
  "summary": "..."
}
```

`source_doc` is mandatory on every record. When more than one document is in the
session — for example a reference example supplied by the user alongside the document
to analyse — it is the only thing that stops content from one leaking into the other.

Never build a deliverable from what you remember of an earlier document in the
conversation. Re-read the page.

## Step 6 — Coverage gate before answering

Before writing the answer or generating a file, verify that **every** page in the hit
list has been either read or explicitly discarded with a reason. If any remain, go back
to step 4.

State the coverage in the answer: how many pages matched, how many were retained, and
which pages could not be extracted.

## Step 7 — Deliverable

Every claim carries its `source_doc` and `page`. For a Word/Excel deliverable, load the
`docx` / `xlsx` skill and build it **from `workspace/<slug>_findings.json`**, not from
the conversation, so the citations cannot drift.

### Professional Word standard (mandatory)

The deliverable must read as a **client-ready relazione**, not a screenshot gallery.

| Required | Forbidden |
|----------|-----------|
| Copertina (titolo, cliente/impianto, data, riservatezza) | Solo elenco immagini senza narrativa |
| Sintesi esecutiva (1–2 paragrafi) | Script python-docx ad hoc se esiste `build_evidence_report.py` |
| Tabella quadro obblighi (ID, sezione, pagina, sintesi) | Full-page `pdftoppm` / screenshot non croppati |
| Sezioni numerate per prescrizione con testo + osservazioni | Indice manuale al posto del corpo analitico |
| Figure numerate «Figura N — …» sotto l'immagine | `add_picture(width=6.5)` senza cap altezza |
| Header/footer con titolo e numerazione pagine | |

Preferred Word workflow when evidence PNGs exist:

1. Collect findings JSON + all `derived/docs/<slug>/evidence/eNNN.png` paths (and sidecars).
2. **Run `scripts/report/build_evidence_report.py`** (after `skill_view("docx")`) — this is the
   default path; do not hand-roll a gallery script unless the template is unavailable.
3. Pass meaningful metadata: `--title`, `--subtitle`, `--client`, `--plant`, `--source-doc`.
4. **Run QA before delivery:** `python scripts/report/qa_evidence_images.py --glob derived/docs/<slug>/evidence/*.png`.
5. Open the output and verify: tables present, sections numbered, figures captioned — not bare PNG stack.

Example:

```bash
python scripts/report/build_evidence_report.py \
  --findings workspace/decreto_findings.json \
  --evidence derived/docs/<slug>/evidence/*.png \
  --output workspace/prescrizioni_rumore_report.docx \
  --title "Prescrizioni autorizzative — Rumore (PIC / PMC)" \
  --subtitle "Estrazione da decreto IPPC" \
  --client "Nome cliente" \
  --plant "Impianto"
```

## Troubleshooting

| Symptom | Action |
|---------|--------|
| `doc_ingest` returns `partial: true` | Call again with `first_page=<resume_from>`. |
| `ocr_failed_pages` is not empty | Retry those pages with `ocr_file(relative_path, first_page=N, last_page=N)`; if OCR is unavailable, say so in the answer. |
| Grep returns nothing | Your pattern is too narrow, or you grepped the wrong root. Confirm with a pattern you know is present, e.g. a word from `first_page_excerpt`. |
| Grep returns `truncated: true` | Split by page range; do not treat it as the full result. |
| Tool timeout | Reduce the page range. Do not repeat the same call unchanged. |
| `pdf_evidence_crop` returns `too_much_whitespace` | Provide a tighter `bbox` in PDF points, or confirm the page has visible content. |
| Evidence QA fails | Re-run `pdf_evidence_crop` with bbox; never ship full-page screenshots. |

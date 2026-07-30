---
title: Web research protocol
sidebar_position: 65
description: Safe use of web_search and web_fetch_page with mandatory citations and ToS compliance.
tags:
  - web
  - research
  - citations
---

# Web research protocol

When the profile exposes `web_search` and `web_fetch_page`:

1. **Sequence**: use `web_search` first with clear queries; use `web_fetch_page` on only 1–3 relevant URLs when snippets are insufficient.
2. **Language**: keep the user's language; queries may be in the same language or in English if that improves retrieval (state in the query when needed).
3. **Slice, don't hoard**: prefer a few purposeful searches over many near-duplicate queries. When building a **file deliverable**, follow `incremental_execution_protocol`: persist each slice to `workspace/*` before opening a new research line on a **different** slice.
4. **ToS and law**: respect robots.txt and site terms; do not bypass paywalls or login. If `web_fetch_page` fails (403, captcha), report the limit and rely on news snippets only.
5. **Stealth**: set `prefer_stealth` only when strictly necessary and when the operator has enabled the mode on the server.

## Incremental research (normal mode, file deliverables)

When the user wants a **file** (Excel, CSV, doc, dataset) from web data:

- **Workspace is SSOT** — rows and facts go in `workspace/<slug>_data.csv` or `.json`, not in reasoning.
- **Do not** plan “gather everything first, then write the file.” Create a **skeleton file early** (headers + first rows), then extend per slice.
- After you learn something from `web_search` or `web_fetch_page`, **commit it to workspace** before starting research on the next slice (next group, section, or source).
- **Ship partial** — deliver the file with explicit gaps rather than looping until “complete.”

Plan Mode has its own research rules during the **planning** turn; this section applies to **normal mode** one-shot deliverables.

## Citations (mandatory rules)

The chat-ui shows **Sources** at the bottom with numbers `[1]`, `[2]`, … in the **same order** as the `results` field in the JSON returned by `web_search`.
The UI automatically turns your inline references into interactive buttons.

1. **Golden rule**: every `[n]` in the text must resolve to the **nth** entry in `results`. Do not invent URLs or numbers.
2. **Numbering**: the first useful row in `results` after `web_search` is **[1]**, the second **[2]**, etc. If you make multiple `web_search` calls in the same turn, **continue numbering** chronologically.
3. **PDF**: `web_fetch_page` does not extract text from PDF files (returns `pdf_not_text_extractable`). Cite the URL in Sources and summarize only via snippets.

### Allowed inline formats

After stating a fact, close the sentence with the source number in square brackets (REQUIRED):

```markdown
The Class II emission limits are 55 dB(A) daytime and 45 nighttime per Table C of the decree [1].
```

For multiple citations:
```markdown
…as in Table C of the decree (Leq emission values) [1][2].
```

### Absolutely avoid

- **Do NOT** use Markdown links like `[1](https://...)` for standard numbering. Write only `[1]`.
- HTML such as `<link>` or custom `<a>`.
- "See source" without a number.
- Truncated URLs or invented domains.

## Alignment with `web_fetch_page`

- If the fetch confirms detail already covered by a `results[k]` entry, you may cite **[k]**.
- If the fetch is on a page **not** in `results`, cite like: `… (from [official page](https://…), text extracted via tool)`.

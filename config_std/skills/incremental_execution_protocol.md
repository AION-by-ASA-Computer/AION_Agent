---
name: incremental_execution_protocol
description: "Step-by-step research and file deliverables in normal mode — workspace as SSOT, ship partial."
tags: [core, protocol, web, deliverable]
status: verified
source: curated
version: 2
---

# Incremental execution protocol

Use this in **normal mode** when the user wants a **file deliverable** (`.xlsx`, `.csv`, `.docx`, report, dataset) built from **external data** (web, APIs, DB exports).

**Do not** use this instead of **Plan Mode** when the request is a multi-step project needing human approval — see `orchestration_protocol` and `core_protocol` rule #8.

**Do not** use this for open-ended deep research — use `trigger_research` when the goal is a long report, not a single workspace file.

## When to load this skill

Call `skill_view("incremental_execution_protocol")` on **skills_hub** when:

- The user asks to **create or update a file** with data you must gather first, and
- You are **not** in Plan Mode planning turn, and
- The work fits in one conversation thread without a sidebar execution plan.

**Mandatory:** load this skill **before** the first web research tool — not after several searches and not only in reasoning.

## Macro-steps (say once, then execute step 1)

Before tools, list **3–6 logical macro-steps** in thinking (see `core_protocol`). Example shapes:

| User ask | Macro-steps |
|----------|-------------|
| “Excel of product prices from vendor sites” | scout → skeleton CSV → slice by category → export xlsx |
| “CSV of public holidays per country” | pick authority source → headers + 2 countries → add regions → final CSV |
| “Report docx from uploaded PDF tables” | inspect PDF → extract table 1 to workspace → table 2 → assemble docx |

## Core idea: workspace is the database

| Store data in | Never store data in |
|---------------|---------------------|
| `workspace/<slug>_data.csv` or `.json` | Reasoning / thinking blocks |
| `workspace/<output>.xlsx` (final) | Chat prose tables |
| Scripts under `workspace/` | Mental compilation across many web calls |

**Reasoning is for choosing the next slice — not for holding rows, scores, or match lists.**

## Workflow (slice by slice)

Work in **slices** (one group, one source, one section, one API page) — not “collect everything, then build.”

### 1 — Orient (minimal)

- One focused `web_search` or known URL if the source is obvious.
- Pick **one** authoritative source or page structure for the slice you are doing **now**.
- Do **not** load office skills (`xlsx`, `docx`, …) until step 2.

### 2 — Skeleton (first commit)

As soon as you have **any** usable fields:

- Create or update `workspace/<slug>_data.csv` (or `.json`) with **headers + rows you already know** (even a handful).
- Tell the user briefly that you are building incrementally.
- **Now** call `skill_view` for the office skill you need (`xlsx`, etc.) if the final format requires it.

### 3 — Fill (repeat per slice)

For each remaining slice:

1. **Research** — `web_search` and/or `web_fetch_page` for **that slice only** (e.g. one group, one standings page).
2. **Commit** — append or merge into `workspace/<slug>_data.*` via `sandbox_write_workspace_file`, `sandbox_edit_workspace_file`, or `sandbox_run_python_file`.
3. **Checkpoint** — optional one line in chat: what was added and what slice is next.

You may use many web tools over the turn; the rule is **persist before changing slice or goal**, not a fixed tool count.

### 4 — Ship

- Produce the final file in `workspace/` (e.g. `.xlsx` via script).
- Reply with: file path, what is complete, and an explicit **gaps** list (missing groups, dates, sources).
- **Partial delivery beats perfectionism** — deliver what you have.

## Anti-patterns (FORBIDDEN)

- “Let me gather all matches/data first” with **no** workspace file until the end.
- Listing tabular data in reasoning across multiple paragraphs.
- Many web calls in a row **without** updating `workspace/*` between slices.
- Loading `skill_view("xlsx")` (or full office skill) before the first data commit.
- Starting a new broad search for “complete dataset” when a partial file already exists — **extend the file** instead.

## Example (product catalog → Excel)

```
user: Build an Excel with product name, price, and URL from public shop pages

1. skill_view("incremental_execution_protocol")
2. web_search → one category (e.g. "laptops site:…")
3. sandbox_write → workspace/products.csv (headers + 3 rows from snippets)
4. skill_view("xlsx") → only now
5. web_fetch_page → one listing page for category A
6. sandbox_run_python_file → append rows to products.csv
7. Repeat 5–6 for category B, or ship partial xlsx + gaps list
8. sandbox_run_python_file → workspace/products.xlsx
```

## Relation to Plan Mode

| Plan Mode | Incremental execution (this skill) |
|-----------|--------------------------------------|
| Sidebar plan + approval | No approval; one-shot deliverable |
| `mark_task_completed` per **task** | Commit per **data slice** to workspace |
| Research budget in **planning** turn only | No global research cap; **sequential** commits |
| Multi-file / architecture | Single deliverable + supporting data files |

If the user’s request is clearly a **project** (many files, phases, approval), use Plan Mode — not this skill.

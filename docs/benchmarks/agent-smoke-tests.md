---
title: Agent smoke tests
sidebar_position: 4
description: How to run the AION agent smoke-test suite from the command line or the admin UI, read its reports and understand its scoring.
---

# Agent smoke tests and diagnostics

The **Agent Smoke Tests** suite is a quick end-to-end check that the AION agent
can really do its everyday jobs: analyze an Excel file, find answers in a long
PDF, and produce a Word document. Use it after an upgrade, a model change or a
profile change to confirm nothing is broken. Administrators can start it from
the admin UI; developers and operators can also run it from the command line.
By default it targets the standard `generic_assistant` profile.

Unlike isolated unit tests, the suite runs the full pipeline (`AgentPipeline`),
uploads real attachments into the session sandboxes, and captures the model's
internal flow live (**reasoning**, **calls to MCP/sandbox tools with their
parameter payloads**, and the **final output**). It then writes detailed
Markdown reports and gives each test a score.

---

## The test cases (`test_config.json`)

The suite includes 3 separate scenarios:

| Test ID | Test name | Assistant | Attachment | Goal |
|---------|-----------|-----------|------------|------|
| `test_1_excel` | **Excel data analysis** | `generic_assistant` | `assets/dataset_vendite.xlsx` | Exact calculation of overall KPIs (revenue, margins, discounts, average order value), 80/20 Pareto analysis by SKU and time trend, using the Python sandbox. |
| `test_2_pdf` | **RAG extraction from a long PDF** | `generic_assistant` | `assets/manuale_tesla.pdf` | Targeted search and extraction (RAG, retrieval-augmented generation) in the Tesla owner's manual: emergency door-opening procedure and brake-fluid service interval. |
| `test_3_word` | **Structured Word document** | `generic_assistant` | _None_ | Creation of a professionally formatted Microsoft Word document (`agenda_kickoff.docx`) with tables and bullet lists. |

:::note
The test names and prompts in `test_config.json` are written in Italian, so the
agent is tested on Italian input.
:::

---

## Run from the admin UI

The suite is fully integrated into the **admin UI** (default port `3870`).

### How to open it
1. Start the backend and the admin UI:
   ```bash
   # Terminal 1 (backend)
   uvicorn src.api.main:app --reload

   # Terminal 2 (admin UI)
   cd admin-ui && pnpm dev
   ```
2. Open `http://localhost:3870/diagnostics` in the browser (or choose
   **Smoke Tests** in the left sidebar).

### What the dashboard offers
- **Profile selector:** choose which agent profile the tests run against.
- **Run / Stop buttons:** start the suite, or stop a run in progress.
- **Live status cards:** duration in seconds, number of tools called and status
  (running / completed / failed) for each scenario.
- **Live console feed (SSE, Server-Sent Events):** shows events as they happen:
  - test started
  - reasoning in progress (with a preview of the thinking block)
  - tool running: `tool_name` (with an expandable view of the JSON parameter payload)
  - test completed
- **Per-test filter:** isolate the log lines of a single test.
- **Markdown report viewer:** shows the formatted report, with options to copy
  it or download the `.md` file.
- **Report history:** a browsable list of all reports saved on disk.

Tests run one after the other.

---

## Run from the command line (CLI)

You can run the suite straight from a terminal, without starting the web server
or any user interface.

### 1. Quick start with PowerShell (Windows)

```powershell
# Standard run (Test 1 -> Test 2 -> Test 3)
.\evals\agent_smoke_tests\run_smoke_tests.ps1

# Run a single specific test
.\evals\agent_smoke_tests\run_smoke_tests.ps1 -Test test_1_excel
```

### 2. Quick start with Bash (Linux / macOS / WSL)

```bash
# Standard run
./evals/agent_smoke_tests/run_smoke_tests.sh

# Run a single test
./evals/agent_smoke_tests/run_smoke_tests.sh --test test_2_pdf
```

The Bash helper passes every argument through to `test_runner.py`, so all the
flags below work with it too.

### 3. Run directly with Python

```bash
# Run with the virtual environment
python evals/agent_smoke_tests/test_runner.py [OPTIONS]
```

#### Available CLI flags

| Flag | Short | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--test <ID>` | `-t <ID>` | String | `None` | Runs only the given test (`test_1_excel`, `test_2_pdf`, `test_3_word`). |
| `--profile <SLUG>` | `-p <SLUG>` | String | `None` (Generic Assistant) | Agent profile slug to run the tests against (e.g. `generic_assistant`, `aion_std`). |
| `--config <PATH>` | `-c <PATH>` | Path | `test_config.json` | Custom path to the JSON configuration file. |
| `--output-dir <DIR>` | `-o <DIR>` | Path | `outputs/` | Directory where the Markdown reports are saved. |
| `--help` | `-h` | Flag | - | Shows the command help. |

---

## Directory layout

All files of the suite live in `evals/agent_smoke_tests/`:

```
evals/agent_smoke_tests/
├── assets/
│   ├── dataset_vendite.xlsx                   # Excel dataset (KPIs & Pareto)
│   └── manuale_tesla.pdf                      # Long PDF manual (RAG)
├── outputs/                                   # Generated Markdown reports (.md)
├── evaluator.py                               # Deterministic scoring engine
├── test_config.json                           # Test case configuration
├── test_runner.py                             # Core execution and streaming script
├── run_smoke_tests.ps1                        # Quick-start helper for PowerShell
└── run_smoke_tests.sh                         # Quick-start helper for Bash/Linux
```

---

## Generated reports

The suite writes its output to `evals/agent_smoke_tests/outputs/`:

1. **Standalone per-test report (`report_<test_id>_<timestamp>.md`):** written
   to disk as soon as each test finishes.
2. **Global suite report (`report_smoke_test_<timestamp>.md`):** updated
   incrementally, live, after each completed test.
3. **Generated documents folder (`outputs/generated_files/<test_id>_<timestamp>/`):**
   collects every file the agent created during the test (`.docx`, `.xlsx`,
   `.pdf` documents, `.png` charts, sandbox scripts, etc.).

### Report format

Reports follow a **chronological timeline** that interleaves the agent's
reasoning blocks with the actual tool calls and their results, in the exact
order they happened. Reports are currently generated in Italian; the excerpt
below shows the real format:

```markdown
# Smoke Test Report: Generazione Word Strutturato

- **ID Test:** `test_3_word`
- **Data Esecuzione:** 2026-09-22 08:35:10
- **Profilo / Assistente:** `generic_assistant`
- **Stato:** ✅ COMPLETATO
- **Tempo di Esecuzione:** 18.4s
- **Tool Chiamati:** 2
- **Prompt Inviato:**
  > Genera un documento Word impaginato...

---

### 📁 Documenti & File nel Workspace di Sessione

| Nome File | Categoria | Dimensione | Percorso / Link |
|---|---|---|---|
| **agenda_kickoff.docx** | Documento | 24.5 KB | [agenda_kickoff.docx](file:///C:/...) (`generated_files/test_3_word_.../agenda_kickoff.docx`) |

---

### ⏱️ Flusso di Esecuzione Cronologico (Timeline)

#### Passo 1 — 🧠 Reasoning
> L'utente chiede di creare un documento Word... Preparo lo script python per python-docx.

#### Passo 2 — 🛠️ Tool: `sandbox_write_workspace_file`
- **Parametri inviati:**
  ```json
  {
    "relative_path": "workspace/make_doc.py",
    "content": "..."
  }
  ```
- **Esito:** ✓ **Eseguito con successo**

#### Passo 3 — 🧠 Reasoning
> Ora eseguo lo script per generare il file agenda_kickoff.docx...

#### Passo 4 — 🛠️ Tool: `sandbox_run_python_file`
- **Parametri inviati:**
  ```json
  {
    "relative_path": "workspace/make_doc.py"
  }
  ```
- **Esito:** ✓ **Eseguito con successo**
- **Risultato:**
  ```
  File agenda_kickoff.docx creato.
  ```

---

### 📝 Risposta Finale dell'Agente
Ho creato il documento Word impaginato e formattato professionalmente...
```

Key to the Italian labels: *ID Test* = test ID, *Data Esecuzione* = run date,
*Profilo / Assistente* = profile / assistant, *Stato* = status, *Tempo di
Esecuzione* = run time, *Tool Chiamati* = tools called, *Prompt Inviato* =
prompt sent, *Passo* = step, *Parametri inviati* = parameters sent, *Esito* =
outcome, *Risultato* = result, *Risposta Finale dell'Agente* = agent's final
answer.

---

## Scoring engine and criteria (`evaluator.py`)

Since version 2.0 of the suite, evaluation does not just check that a test
finished without exceptions: it analyzes the output with a **deterministic,
static scoring engine** implemented in `evals/agent_smoke_tests/evaluator.py`.

### How scoring works
- **No LLM-as-a-judge:** the verdict is not delegated to another language model
  (avoiding the cost, latency and hallucinations of a model-based judge).
- **Direct checks and file inspection:** the engine checks the generated files
  (e.g. parsing the XML tree `word/document.xml` of `.docx` files, presence and
  resolution of `.png` images), the tool calls actually made, and whether the
  numbers are correct within a percentage tolerance (accepting both Italian and
  international number formats).
- **0–100 score and grades:** each scenario has **10 weighted micro-criteria**
  that add up to a final score out of 100, mapped to a grade:

| Grade | Score | Result | Meaning |
|:---:|:---:|:---:|:---|
| 🎯 **A+** | 90 – 100 pt | ✅ Passed | Excellent: all KPIs, deliverables and formatting are perfect. |
| 🎯 **A** | 80 – 89 pt | ✅ Passed | Very good: meets every key requirement with minor secondary inaccuracies. |
| 🎯 **B** | 70 – 79 pt | ✅ Passed | Good: deliverables generated and correct, a few small details missing. |
| 🎯 **C** | 60 – 69 pt | ✅ Passed | Sufficient: reaches the minimum pass mark (≥ 60 pt). |
| ❌ **F** | 0 – 59 pt | ❌ Failed | Not passed: wrong calculations, tools not called or files missing. |

---

### Criteria by scenario

#### 📊 Test 1: Excel data analysis (`test_1_excel` — 100 pt)

| # | Criterion | Category | Points | Check & target value |
|:---:|:---|:---:|:---:|:---|
| **1** | **Python sandbox execution** | `tool` | **10 pt** | Call to a sandbox tool (`sandbox_run_python_file`, `sandbox_execute_python`). |
| **2** | **Total net revenue (2025)** | `data` | **15 pt** | Correct value within 2% tolerance: **~497,412 €** (or overall total **~954,925 €**). |
| **3** | **Total margin (€)** | `data` | **10 pt** | Correct value: **~191,134 €** (2025) or **~368,618 €** (total). |
| **4** | **Average order value (AOV)** | `data` | **10 pt** | Correct value: **~1,042 €** (2025) or **~1,066 €** (total). |
| **5** | **Best sales agent** | `data` | **10 pt** | Top performer identified: **Luca Moretti** (~133k €) or **Marco Rossi** (~108k €). |
| **6** | **Peak month** | `data` | **10 pt** | Month with the highest sales identified: **December** (or **Q4**). |
| **7** | **Top 5 items / SKUs** | `data` | **10 pt** | The leading products are listed (e.g. *Server Rack Enterprise*, *Firewall Hardware X*). |
| **8** | **Agent performance chart** | `file` | **10 pt** | Image file `chart_agents_2025.png` generated, or `render_chart` tool used. |
| **9** | **Monthly trend chart** | `file` | **10 pt** | Image file `chart_trend_mensile_2025.png` generated, or `render_chart` tool used. |
| **10** | **Actionable bullet-point summary** | `formatting` | **5 pt** | At least 3 numbered/bulleted conclusions or recommendations. |

---

#### 📄 Test 2: RAG extraction from a long PDF (`test_2_pdf` — 100 pt)

| # | Criterion | Category | Points | Check & target value |
|:---:|:---|:---:|:---:|:---|
| **1** | **RAG / ingest tool call** | `tool` | **10 pt** | Use of document reading and search tools (`khub_rag_search`, `doc_ingest`, etc.). |
| **2** | **Manual door-opening procedure** | `data` | **15 pt** | Emergency sequence for the front doors extracted. |
| **3** | **Mechanical release reference** | `data` | **10 pt** | Explicit mention of the mechanical release or lever in front of the window switches. |
| **4** | **Lowering the window** | `data` | **10 pt** | Mention of the warning to lower the window to avoid damage. |
| **5** | **Emergency-only warning** | `data` | **10 pt** | States that the manual release is only for a complete loss of power. |
| **6** | **Brake-fluid service interval** | `data` | **15 pt** | Correct interval: **every 2 years** or **40,000 km / 25,000 miles**. |
| **7** | **Brake-fluid contamination check** | `data` | **10 pt** | Mention of the contamination test or fluid replacement. |
| **8** | **Manual page or section reference** | `data` | **10 pt** | Precise citation of the manual chapter/section (e.g. *Maintenance*, *Doors*). |
| **9** | **Clear safety instructions** | `formatting` | **5 pt** | Text formatted with clear bullet lists or numbered steps. |
| **10** | **Overall technical summary** | `formatting` | **5 pt** | Complete answer with no fragments or gaps on either question. |

---

#### 📝 Test 3: Structured Word document (`test_3_word` — 100 pt)

| # | Criterion | Category | Points | Check & target value |
|:---:|:---|:---:|:---:|:---|
| **1** | **Sandbox generation tool** | `tool` | **10 pt** | Script run to build the Word file (`python-docx`, sandbox writes). |
| **2** | **`agenda_kickoff.docx` created** | `file` | **20 pt** | `.docx` file physically generated and present in the session workspace. |
| **3** | **Meeting header / title** | `data` | **10 pt** | Official title present (e.g. *Kickoff Meeting Aziendale* / *Riunione*). |
| **4** | **Meeting date (15 October)** | `data` | **10 pt** | Date given in the prompt (**15 Ottobre**) included in the body or header. |
| **5** | **Agenda table** | `data` | **15 pt** | XML check that a real table element (`<w:tbl>`) exists in the document. |
| **6** | **Required table columns** | `data` | **10 pt** | Exact columns present: **Orario** (time), **Argomento** (topic), **Relatore** (speaker), checked in the XML. |
| **7** | **Bullet list of required materials** | `data` | **10 pt** | Bullet list of preparatory materials for participants. |
| **8** | **Valid DOCX XML structure** | `file` | **5 pt** | The DOCX ZIP archive is intact and its internal XML tree is valid. |
| **9** | **Realistic document size** | `file` | **5 pt** | Generated file larger than 2 KB (rules out empty or corrupted files). |
| **10** | **Final confirmation message** | `formatting` | **5 pt** | A clear final message summarizing the structure of the deliverable. |

---

## Backend API endpoints (FastAPI)

All endpoints live under the `/admin/diagnostics` prefix (admin access
required):

| Method & path | What it does |
|---------------|--------------|
| `POST /admin/diagnostics/run-tests` and `GET /admin/diagnostics/run-tests` | Runs the suite and streams Server-Sent Events (`text/event-stream`). Query parameters: `test_id` (optional, run a single test) and `profile` (optional, profile slug or name). The admin UI also passes its token as `access_token`. |
| `POST /admin/diagnostics/cancel` | Promptly stops the diagnostic run in progress. |
| `GET /admin/diagnostics/config` | Returns the active configuration from `test_config.json`. |
| `GET /admin/diagnostics/reports` | Lists the reports saved in `evals/agent_smoke_tests/outputs/`. |
| `GET /admin/diagnostics/reports/{filename}` | Returns the content of the requested report. |
| `GET /admin/diagnostics/file` | Resolves and serves deliverables, reports and PNG images produced in the test sessions (`path`, `session_id`, `download`). |

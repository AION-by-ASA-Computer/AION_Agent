---
title: Agent Smoke Tests & Diagnostics
sidebar_position: 4
description: Guida completa alla suite di smoke test diagnostici per l'agente AION (Generic Assistant), esecuzione da CLI e Admin UI.
---

# Agent Smoke Tests & Diagnostics

La suite **Agent Smoke Tests** è il framework di validazione rapida e diagnostica per verificare le capacità operative end-to-end dell'agente AION (profilo standard `generic_assistant`).

A differenza dei test unitari isolati, la suite esegue l'intera pipeline (`AgentPipeline`), carica allegati reali nelle sandbox di sessione, e intercetta in tempo reale il flusso interno dell'LLM (**Reasoning**, **chiamate a tool MCP/Sandbox con payload parametri** e **Output Finale**), generando report Markdown dettagliati.

---

## Struttura Directory

Tutti i file della suite sono organizzati nella cartella `evals/agent_smoke_tests/`:

```
evals/agent_smoke_tests/
├── assets/
│   ├── Dataset_Test_BI_Vendite_AI_Agent.xlsx  # Dataset Excel (KPI & Pareto)
│   ├── dataset_vendite.xlsx                   # Alias per test_config.json
│   ├── Tesla_Owner_Manual.pdf                 # Manuale PDF lungo (RAG)
│   └── manuale_tesla.pdf                      # Alias per test_config.json
├── outputs/                                   # Report Markdown generati (.md)
├── test_config.json                           # Configurazione dei casi di test
├── test_runner.py                             # Script core di esecuzione e streaming
├── run_smoke_tests.ps1                        # Helper di avvio rapido per PowerShell
└── run_smoke_tests.sh                         # Helper di avvio rapido per Bash/Linux
```

---

## I Casi di Test (`test_config.json`)

La suite include 3 scenari operativi distinti:

| ID Test | Nome Test | Assistente | Allegato | Obiettivo Operativo |
|---------|-----------|------------|----------|---------------------|
| `test_1_excel` | **Analisi Dati Excel** | `generic_assistant` | `assets/dataset_vendite.xlsx` | Calcolo esatto KPI generali (Fatturato, Margini, Sconti, AOV), analisi Pareto 80/20 su SKU e trend temporale tramite Python Sandbox. |
| `test_2_pdf` | **Estrazione RAG da PDF lungo** | `generic_assistant` | `assets/manuale_tesla.pdf` | Ricerca mirata ed estrazione nel manuale Tesla: procedura di emergenza apertura portiera e intervallo cambio liquido freni. |
| `test_3_word` | **Generazione Word Strutturato** | `generic_assistant` | _Nessuno_ | Creazione di un documento Microsoft Word (`agenda_kickoff.docx`) formattato e impaginato professionalmente con tabelle ed elenchi. |

---

## Esecuzione da Linea di Comando (CLI)

La suite può essere eseguita direttamente da terminale senza avviare il server web né le interfacce grafiche.

### 1. Avvio Rapido con PowerShell (Windows)

```powershell
# Esecuzione standard (Test 1 -> Test 2 -> Test 3)
.\evals\agent_smoke_tests\run_smoke_tests.ps1

# Esecuzione di un singolo test specifico
.\evals\agent_smoke_tests\run_smoke_tests.ps1 -Test test_1_excel
```

### 2. Avvio Rapido con Bash (Linux / macOS / WSL)

```bash
# Esecuzione standard
./evals/agent_smoke_tests/run_smoke_tests.sh

# Esecuzione singolo test
./evals/agent_smoke_tests/run_smoke_tests.sh --test test_2_pdf
```

### 3. Avvio Diretto con Python

```bash
# Esecuzione con il virtual environment
python evals/agent_smoke_tests/test_runner.py [OPZIONI]
```

#### Parametri e Flag CLI Disponibili

| Flag | Abbreviazione | Tipo | Default | Descrizione |
|------|---------------|------|---------|-------------|
| `--test <ID>` | `-t <ID>` | String | `None` | Esegue esclusivamente il test specificato (`test_1_excel`, `test_2_pdf`, `test_3_word`). |
| `--config <PATH>` | `-c <PATH>` | Path | `test_config.json` | Percorso personalizzato per il file di configurazione JSON. |
| `--output-dir <DIR>` | `-o <DIR>` | Path | `outputs/` | Directory in cui salvare i report Markdown generati. |
| `--help` | `-h` | Flag | - | Mostra la guida dei comandi. |

---

## Esecuzione da Admin UI (Dashboard Web)

La suite è completamente integrata nel pannello di amministrazione **Admin UI** (porta standard `3870`).

### Come Accedere
1. Avvia il backend e l'Admin UI:
   ```bash
   # Terminale 1 (Backend)
   uvicorn src.api.main:app --reload

   # Terminale 2 (Admin UI)
   cd admin-ui && pnpm dev
   ```
2. Apri il browser su `http://localhost:3870/diagnostics` (o seleziona la voce **Smoke Tests** nella barra laterale sinistra).

### Funzionalità della Dashboard
- **Card di Stato Real-time:** Visualizzano durata in secondi, conteggio tool chiamati e stato (In corso / Completato / Fallito).
- **Toggle Esecuzione Parallela:** Permette di alternare tra esecuzione sequenziale e concorrente multi-sessione.
- **Console Feed Live (SSE):** Riceve e mostra gli eventi in tempo reale con icone intuitive:
  - ⏳ *Inizio test...*
  - ⚙️ *Ragionamento in corso...* (con anteprima del blocco di pensiero)
  - 🛠️ *Esecuzione tool: [nome_tool]* (con visualizzatore a comparsa del payload JSON dei parametri)
  - ✅ *Test completato.*
- **Filtro per Singolo Test:** Permette di isolare i log del test desiderato anche durante l'esecuzione parallela.
- **Visualizzatore Report Markdown:** Visualizza il report formattato con opzioni per copiare o scaricare il file `.md`.
- **Storico Report:** Elenco navigabile di tutti i report salvati su disco con accesso immediato.

---

## Struttura dei Report Markdown Generati

La suite genera due tipologie di report in `evals/agent_smoke_tests/outputs/`:

1. **Report Autonomo per Singolo Test (`report_<test_id>_<timestamp>.md`):** Creato e scritto su disco immediatamente al termine del singolo test.
2. **Report Globale della Suite (`report_smoke_test_<timestamp>.md`):** Aggiornato incrementalmente in tempo reale ad ogni test completato.
3. **Cartella Documenti Generati (`outputs/generated_files/<test_id>_<timestamp>/`):** Raccoglie tutti i file creati dall'agente durante il test (documenti `.docx`, `.xlsx`, `.pdf`, grafici `.png`, script sandbox, ecc.).

### Formato dei Report

I report presentano una struttura a **Timeline Cronologica** che intercala i blocchi di pensiero dell'agente con le effettive invocazioni dei tool e i rispettivi risultati nell'ordine temporale esatto:

```markdown
# Smoke Test Report: Generazione Word Strutturato

- **ID Test:** `test_3_word`
- **Data Esecuzione:** 2026-09-22 08:35:10
- **Assistente:** Generic Assistant (`generic_assistant`)
- **Stato:** ✅ COMPLETATO
- **Tempo di Esecuzione:** 18.4s
- **Tool Chiamati:** 2
- **Prompt Inviato:**
  > Genera un documento Word impaginato...

---

### 📁 Documenti & File Generati

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

---

## Motore di Valutazione & Criteri di Scoring (`evaluator.py`)

A partire dalla versione 2.0 della suite, la valutazione non si limita a verificare se il test è terminato senza eccezioni, ma analizza l'output attraverso un **motore di scoring statico deterministico** implementato in [`evals/agent_smoke_tests/evaluator.py`](file:///c:/Users/ACOLOMBO/OneDrive%20-%20AION/Desktop/Progetti/AION_Agent/evals/agent_smoke_tests/evaluator.py).

### Filosofia del Motore di Valutazione
- **Zero LLM-as-a-Judge:** La valutazione non delega il giudizio a un altro modello linguistico (evitando costi, latenze e allucinazioni del valutatore).
- **Controllo Diretto & Ispezione Fisica:** Vengono verificati i file generati (es. parsing XML dell'albero `word/document.xml` per i `.docx`, presenza e risoluzione immagini `.png`), invocazioni tool effettive e conformità dei calcoli matematici con tolleranza percentuale (es. formato numerico italiano ed internazionale).
- **Scoring 0–100 & Gradi:** Ogni scenario prevede **10 micro-criteri pesati** che compongono un punteggio finale su base 100 con attribuzione di un grado:

| Grado | Punteggio | Esito | Significato |
|:---:|:---:|:---:|:---|
| 🎯 **A+** | 90 – 100 pt | ✅ Superato | Eccellente: tutti i KPI, deliverable e formattazioni sono perfetti. |
| 🎯 **A** | 80 – 89 pt | ✅ Superato | Ottimo: rispetta tutti i requisiti chiave con minime imprecisioni secondarie. |
| 🎯 **B** | 70 – 79 pt | ✅ Superato | Buono: deliverable generati e corretti, piccoli dettagli omessi. |
| 🎯 **C** | 60 – 69 pt | ✅ Superato | Sufficiente: raggiunge la soglia minima di superamento (≥ 60 pt). |
| ❌ **F** | 0 – 59 pt | ❌ Fallito | Non superato: calcoli errati, tool non invocati o file mancanti. |

---

### Tabella Criteri di Valutazione per Scenario

#### 📊 Test 1: Analisi Dati Excel (`test_1_excel` — 100 pt)

| # | Criterio | Categoria | Punti | Regola di Verifica & Valore Target |
|:---:|:---|:---:|:---:|:---|
| **1** | **Esecuzione Sandbox Python** | `tool` | **10 pt** | Invocazione di tool sandbox (`sandbox_run_python_file`, `sandbox_execute_python`). |
| **2** | **Fatturato Netto Totale (2025)** | `data` | **15 pt** | Valore numerico corretto con tolleranza 2%: **~497.412 €** (o totale **~954.925 €**). |
| **3** | **Margine Totale (€)** | `data` | **10 pt** | Valore numerico corretto: **~191.134 €** (2025) o **~368.618 €** (Totale). |
| **4** | **Scontrino Medio (AOV)** | `data` | **10 pt** | Valore numerico corretto: **~1.042 €** (2025) o **~1.066 €** (Totale). |
| **5** | **Performance Miglior Agente** | `data` | **10 pt** | Identificazione del top performer: **Luca Moretti** (~133k €) o **Marco Rossi** (~108k €). |
| **6** | **Mese di Picco** | `data` | **10 pt** | Identificazione del mese con vendite massime: **Dicembre** (o **Q4**). |
| **7** | **Top 5 Articoli / SKU** | `data` | **10 pt** | Presenza dei prodotti trainanti (es. *Server Rack Enterprise*, *Firewall Hardware X*). |
| **8** | **Grafico Performance Agenti** | `file` | **10 pt** | Generazione del file immagine `chart_agents_2025.png` o tool `render_chart`. |
| **9** | **Grafico Trend Mensile** | `file` | **10 pt** | Generazione del file immagine `chart_trend_mensile_2025.png` o tool `render_chart`. |
| **10** | **Sintesi Bullet Point Operativi** | `formatting` | **5 pt** | Presenza di almeno 3 conclusioni o raccomandazioni operative numerate/puntate. |

---

#### 📄 Test 2: Estrazione RAG da PDF Lungo (`test_2_pdf` — 100 pt)

| # | Criterio | Categoria | Punti | Regola di Verifica & Valore Target |
|:---:|:---|:---:|:---:|:---|
| **1** | **Invocazione Tool RAG / Ingest** | `tool` | **10 pt** | Uso di tool di lettura e ricerca documentale (`khub_rag_search`, `doc_ingest`, ecc.). |
| **2** | **Procedura Apertura Manuale Portiera** | `data` | **15 pt** | Estrazione della sequenza di emergenza per le portiere anteriori. |
| **3** | **Riferimento Maniglia Meccanica** | `data` | **10 pt** | Menzione esplicita dello sblocco o levetta meccanica davanti ai pulsanti finestrino. |
| **4** | **Abbassamento Finestrino** | `data` | **10 pt** | Menzione dell'avvertenza di abbassamento del finestrino per evitare rotture. |
| **5** | **Avvertenza Emergenza (Non Uso Normale)** | `data` | **10 pt** | Evidenza che lo sblocco manuale è riservato a casi di assenza totale di alimentazione. |
| **6** | **Frequenza Manutenzione Liquido Freni** | `data` | **15 pt** | Controllo corretto dell'intervallo: **ogni 2 anni** oppure **40.000 km / 25.000 miglia**. |
| **7** | **Controllo Contaminazione Freni** | `data` | **10 pt** | Menzione del test di contaminazione o sostituzione del liquido. |
| **8** | **Riferimento Pagina o Sezione Manuale** | `data` | **10 pt** | Citazione precisa del capitolo/sezione del manuale (es. *Manutenzione*, *Porte*). |
| **9** | **Chiarezza Istruzioni di Sicurezza** | `formatting` | **5 pt** | Testo formattato con elenchi puntati o passaggi numerati chiari. |
| **10** | **Sintesi Tecnica Generale** | `formatting` | **5 pt** | Risposta esauriente senza frammentazioni o omissioni sui due quesiti. |

---

#### 📝 Test 3: Generazione Word Strutturato (`test_3_word` — 100 pt)

| # | Criterio | Categoria | Punti | Regola di Verifica & Valore Target |
|:---:|:---|:---:|:---:|:---|
| **1** | **Tool Generazione Sandbox** | `tool` | **10 pt** | Invocazione di script per compilare file Word (`python-docx`, scrittura sandbox). |
| **2** | **Creazione File `agenda_kickoff.docx`** | `file` | **20 pt** | File `.docx` fisicamente generato e presente nel workspace della sessione. |
| **3** | **Intestazione / Titolo Riunione** | `data` | **10 pt** | Presenza del titolo ufficiale (es. *Kickoff Meeting Aziendale* / *Riunione*). |
| **4** | **Data Riunione (15 Ottobre)** | `data` | **10 pt** | Data specificata nel prompt (**15 Ottobre**) inserita nel corpo o nell'intestazione. |
| **5** | **Tabella Ordine del Giorno** | `data` | **15 pt** | Verifica XML presenza reale dell'elemento tabella (`<w:tbl>`) nel documento. |
| **6** | **Colonne Tabella Richieste** | `data` | **10 pt** | Colonne esatte presenti: **Orario**, **Argomento**, **Relatore** (verificate da XML). |
| **7** | **Elenco Puntato Materiali Richiesti** | `data` | **10 pt** | Presenza di elenchi puntati con i materiali preparatori per i partecipanti. |
| **8** | **Struttura XML Valida DOCX** | `file` | **5 pt** | Integrità dell'archivio ZIP del file DOCX e validità dell'albero XML interno. |
| **9** | **Dimensione Documento Reale** | `file` | **5 pt** | Dimensione del file generato superiore a 2 KB (evita file vuoti o corrotti). |
| **10** | **Risposta Finale di Conferma** | `formatting` | **5 pt** | Messaggio finale chiaro che riassume la struttura del deliverable prodotto. |

---

## Backend API Endpoints (`FastAPI`)

Tutti gli endpoint risiedono sotto il prefisso `/admin/diagnostics`:

- `POST /admin/diagnostics/run-tests` & `GET /admin/diagnostics/run-tests`
  - Stream Server-Sent Events (`text/event-stream`).
  - Query parameters: `parallel` (bool), `test_id` (string opzionale), `access_token` (string auth).
- `POST /admin/diagnostics/cancel`
  - Interrompe tempestivamente l'esecuzione attiva dei test diagnostici in corso.
- `GET /admin/diagnostics/config`
  - Restituisce la configurazione attiva da `test_config.json`.
- `GET /admin/diagnostics/reports`
  - Restituisce l'elenco dei report salvati in `evals/agent_smoke_tests/outputs/`.
- `GET /admin/diagnostics/reports/{filename}`
  - Restituisce il contenuto del report richiesto.
- `GET /admin/diagnostics/file`
  - Risolve e distribuisce file deliverable, report e immagini PNG generate nelle sessioni di test (`path`, `session_id`, `download`).


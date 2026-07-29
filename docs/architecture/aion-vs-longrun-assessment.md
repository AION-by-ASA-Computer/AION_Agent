---
title: AION nativo vs Long-Run Mode (Pi Agent) — Valutazione tecnica
sidebar_position: 20
description: Analisi comparativa reale (basata su lettura del codice) tra il backend AION nativo e la long-run mode Pi Agent, con verdetto su dove investire e piano di modifiche.
---

# AION nativo vs Long-Run Mode (Pi Agent) — Valutazione tecnica

> Documento di analisi. Nessuna modifica al codice è stata effettuata: tutte le
> affermazioni sono verificate leggendo lo stato attuale del repository (incluse
> le modifiche non committate in `feat-harness-aion-v2`) e citano `file:riga`.
> Data: 2026-07-27.

## 1. Executive summary

| Dimensione | AION nativo | Long-Run Mode (Pi) |
|---|---|---|
| **Velocità** | ✅ Strutturalmente più veloce: tool call in-process, parallelismo reale via `ThreadPoolExecutor` di Haystack | ❌ 2+ hop di rete extra per ogni tool call (Python↔Node NDJSON + Node↔Python invoke), overhead per-evento sul token stream |
| **Solidità harness** | ⚠️ Compattazione **distruttiva** (DELETE reale su DB), nessun circuit breaker su tool falliti ripetutamente | ✅ Resume/cold-start hydration, stale-turn cleanup, circuit breaker anti-loop, compattazione cumulativa con offload pointer |
| **Qualità/robustezza compattazione** | ⚠️ Due implementazioni parallele (mid-turn sync vs fallback v2), solo una integra ledger/offload | ✅ Compattazione delega al backend Python condiviso, arricchita con ledger+offload, ma con fallback silenzioso non osservabile |
| **Rischi architetturali** | Race condition su registry condiviso, nessun cleanup file offloaded | Sessioni Pi **solo in-memory** (SPOF), budget tool-call **non applicato** (dead code), stato circuit breaker non per-sessione |
| **Complessità operativa** | Bassa — un solo processo | Alta — servizio Node separato, dipendenza npm closed-source (`@earendil-works/pi-coding-agent`), autenticazione a shared-secret |

**Verdetto**: conviene investire principalmente sul **backend AION nativo**,
portandoci sopra i pattern di solidità che oggi esistono solo in Pi (circuit
breaker, compattazione non distruttiva, integrazione piena con ledger/offload).
Il motivo è che il gap di velocità di Pi è strutturale (hop di rete extra,
dipendenza closed-source) e difficilmente colmabile, mentre il gap di
solidità del nativo è fatto di bug/gap implementativi puntuali, risolvibili
senza redesign. Vedi [§6](#6-verdetto-esteso) per il ragionamento completo.

---

## 2. Nota metodologica

L'analisi è stata condotta leggendo il codice sorgente reale (non solo la
documentazione) dei due path, inclusi i moduli nuovi/non committati che hai
appena introdotto per l'offload dei risultati dei tool (`tool_offload.py`,
`tool_ledger.py`, `llm_limits.py`, `pi_compaction.py`, `tool_circuit.py`,
`aion-compaction.ts`, `aion-ledger.ts`), i relativi test, e i diff rispetto
allo stato precedente. Dove documentazione e implementazione divergono, è
segnalato esplicitamente.

**Chiarimento importante sul marker di compattazione**: hai riportato che in
chat appare un placeholder tipo `[AION COMPACTED]`. Questa stringa esatta
**non esiste nel codice attuale** (verificato con grep su tutto il repo). Il
marker realmente prodotto dal path nativo è:

```
[AION COMPACTION — contesto precedente sintetizzato]
```

definito in `src/memory/context_compressor.py:18` e iniettato da
`format_compaction_block()` (`turn_compaction.py:142-152`). Potrebbe essere:
(a) una versione precedente/diversa del testo che hai visto, oppure (b) un
evento SSE `context_compacting` renderizzato lato UI con label diversa
(`chat-ui/lib/i18n/locales/it.json:357-358`, `"Compattazione in corso…"`).
**Domanda aperta per te**: puoi confermare se il testo che vedi oggi è quello
sopra, o è cambiato? Questo aiuta a capire se il problema è nel marker (cosmetico)
o nella perdita di contenuto sottostante (sostanziale, vedi §3.1).

---

## 3. Backend AION nativo

### 3.1 Compattazione — come funziona davvero

Due meccanismi in `src/runtime/turn_compaction.py`, entrambi innescati da
`maybe_compact_after_tool()` (linea 1055), chiamata dopo ogni `tool_end`/`tool_error`
(`src/main.py:363`):

- **Mid-turn sync** (`_sync_compact_head_tail`, linee 701-750): trigger quando
  `total_tokens >= max_prompt * AION_CONTEXT_COMPRESS_MID_TURN_RATIO` (default
  `0.92`). Prende la parte più vecchia della conversazione, la fa riassumere
  dall'LLM, e la **sostituisce fisicamente** con un unico messaggio contenente
  il blocco `<summary>`.
- **Fallback meccanico** (`mechanical_shrink_conversation`, linee 603-637):
  sostituisce i body dei tool message più vecchi con un placeholder statico
  ("Earlier tool output removed…") senza passare dall'LLM.

**Il problema reale non è il marker, è che la compattazione è distruttiva a
livello di database.** `compact_agent_messages_in_place()` (linea 911-915)
chiama `history_manager.persist_stm_compaction()`
(`src/data/history_bridge.py:798-890`), che esegue un **DELETE SQL reale**
via `_delete_messages_and_children()` sui messaggi non mantenuti nella coda
`keep_last_n`. Non esiste soft-delete, tombstone o archiviazione — i messaggi
originali spariscono dalla tabella `messages`. L'unica traccia superstite è
il riassunto generato dall'LLM: se è impreciso o tronca dettagli, quei
dettagli sono **persi in modo irrecuperabile**, e l'utente non ha modo di
"espandere" la cronologia compattata in UI. Questo spiega esattamente la tua
osservazione ("perde info", "scompare la cronologia").

Un secondo gap concreto: solo il ramo `compact_memory_fallback` (path v2,
`src/runtime/compaction/policy.py:44-73`) arricchisce il riassunto con
`render_ledger_table()` + `offload_paths_for_session()`. Il ramo **più usato**,
`_sync_compact_head_tail`, **non lo fa** — quindi con l'offload attivo, un
tool result appena spostato su disco può comunque "sparire" dalla vista
dell'LLM dopo una compattazione mid-turn, perché quel ramo non include la
tool-trace nel transcript da riassumere.

### 3.2 Sistema di offload/ledger (nuovo)

- **Offload (L1)**, `src/runtime/tool_offload.py`: risultati tool > `AION_TOOL_OFFLOAD_MIN_CHARS`
  (default 8000) vengono scritti su
  `data/sessions/<sid>/derived/tool_results/{seq}_{tool}_{call_id}.txt`, e nel
  contesto LLM resta solo un pointer + preview. `web_search` escluso di default.
  Cap storage 64MB/sessione con pruning oldest-first.
- **Ledger (L2)**, `src/runtime/tool_ledger.py`: JSONL append-only, una riga
  per tool call, renderizzato in prompt via `render_ledger_table()` — iniettato
  nel path nativo direttamente in `src/runtime/turn/turn_context.py:531-542`.
- Entrambi **feature-flagged, default OFF** (`AION_TOOL_OFFLOAD_ENABLED=0`,
  `AION_TOOL_LEDGER_ENABLED=0`) — zero rischio di regressione se non attivati.
- **Sono infrastruttura genuinamente condivisa**: `process_tool_result_for_context()`
  (`tool_offload.py:314-347`) è l'unico punto d'ingresso, chiamato sia dal path
  nativo (`turn_compaction.py:1055-1061`) sia dal path Pi
  (`src/api/internal/pi_tools.py:90,102-109`). Stesso ledger JSONL, stessa
  directory di offload per entrambi i backend.

### 3.3 Punti di forza confermati

- **Parallelismo reale**: il path nativo usa `haystack.components.tools.tool_invoker.ToolInvoker`,
  che esegue le tool call in un `ThreadPoolExecutor` (default `max_workers=4`)
  sia in `run()` che `run_async()`. Non è codice custom AION, ma è realmente
  cablato e attivo — spiega perché percepisci risposte più rapide e più tool
  in parallelo.
- Offload/ledger ben testati a livello unitario (19/20 test passano) e con
  protezioni contro path traversal (`sanitize_slug`, `safe_resolve`).

### 3.4 Debolezze concrete

1. **Compattazione distruttiva senza recupero** (§3.1) — il problema principale
   che hai segnalato.
2. **Ramo mid-turn non integrato con ledger/offload** (§3.1) — rischio di perdere
   riferimenti ai risultati offloaded proprio durante la compattazione più frequente.
3. **Nessun circuit breaker** per tool che falliscono ripetutamente con lo
   stesso errore (`tool_args_truncated`, generato da `mcp_tool_args.py:183-187`
   in entrambi i path, ma consumato da un breaker solo lato Pi — vedi §4.3).
4. **Race condition potenziale**: `_TURN_RUNTIME_REGISTRY` (`turn_compaction.py:28`)
   è un dict globale condiviso tra il task SSE e il task figlio di `agent.run`,
   senza lock — commento nel codice stesso riconosce il rischio (linee 26-27).
5. **Nessun cleanup automatico** dei file offloaded quando una sessione viene
   cancellata — promesso in `docs/architecture/context-offloading.md:274`
   ("Cleanup on session deletion") ma non implementato: rischio di crescita
   disco indefinita.
6. **Bug verificato nei test**: `test_pi_fingerprint_changes_with_max_tokens`
   (`src/test/test_llm_limits.py:47-54`) fallisce — il fingerprint di config
   Pi non si invalida quando cambia solo `AION_CHAT_MAX_TOKENS` senza override
   esplicito di `AION_LONG_RUN_MAX_TOKENS` (`llm_limits.py:11-31,65-72`).
   Impatta entrambi i path perché è codice condiviso.
7. Le nuove env var (`AION_TOOL_OFFLOAD_*`, `AION_TOOL_LEDGER_*`) sono lette
   via `os.getenv` diretto invece che tramite `AionSettings` (`src/settings.py`),
   incoerente con lo stile del resto del progetto.

---

## 4. Long-Run Mode (Pi Agent)

### 4.1 Architettura e perché è più lenta

- Protocollo Python↔Node: **HTTP + NDJSON streaming**, non SSE
  (`PiWorkerClient.stream_prompt`, `src/runtime/pi_runtime/pi_client.py:81-119`;
  lato Node, `services/pi-long-run/src/server.ts:120-147`). L'SSE verso il
  browser viene ricostruito a valle in `pi_turn_runner.run_pi_agent_turn`
  (`pi_turn_runner.py:315-349`).
- **Ogni tool call paga un round-trip HTTP aggiuntivo**: LLM → loop Pi
  (pacchetto npm closed-source `@earendil-works/pi-coding-agent`, non nel
  repo) → `fetch` Node→Python (`aion-bridge.ts:63-83`) → FastAPI
  `/internal/pi/tools/invoke` (`src/api/internal/pi_tools.py:83-144`) → MCP/tool
  nativo → stesso percorso a ritroso. Rispetto al path nativo (chiamata
  Python in-process), sono **almeno 2 hop di rete extra per tool call** — questo
  spiega strutturalmente la latenza percepita, indipendentemente da eventuale
  inefficienza di codice.
- Overhead per-evento: ogni riga NDJSON ("token"/"reasoning") triggera
  `count_tokens()` + `record_pi_context_delta()` + eventuale `queue.put()`
  (`_pi_track_stream_tokens`, `pi_turn_runner.py:121-149`) — lavoro Python
  fine-grained su un hot path che il loop nativo non ha nella stessa forma.
- **Sessioni Pi sono solo in-memory** lato Node (`session-factory.ts:34`,
  `Map<string, ManagedSession>`) — nessuna persistenza; un riavvio del worker
  Node perde tutte le sessioni attive.
- Sul parallelismo dei tool: **non verificabile da questo repo** — è
  interamente controllato dentro il pacchetto npm closed-source. Quello che
  è verificabile è che, anche se Pi parallelizza internamente, ogni tool call
  serializza comunque attraverso `_invoke_mcp_tool`/`_invoke_native_tool`
  (`src/runtime/pi_runtime/tool_invoke.py:51-147`), che non usa `asyncio.gather`
  da nessuna parte.

### 4.2 Compattazione — perché è "più solida"

`aion-compaction.ts` aggancia l'hook nativo di Pi `session_before_compact`
(linea 21) e, se `AION_PI_CUSTOM_COMPACTION` è attivo, delega il riassunto al
backend Python (`/internal/pi/compaction/summarize` →
`pi_compaction.summarize_for_pi_compaction`, `src/runtime/pi_runtime/pi_compaction.py:93-123`).
**Non è una compattazione Pi-nativa "magica"**: usa lo stesso
`complete_text_sync` e lo stesso prompt di sintesi del path nativo, ma con
due differenze reali che la rendono più robusta:

1. **Accumula stato tra compattazioni successive** via `_merge_details`
   (`pi_compaction.py:36-64`) — dedupe + cap `[-80:]` su file letti/modificati,
   tool ledger, offload path — invece di ripartire da zero ad ogni
   compattazione come sembra fare il path nativo.
2. **Fallback silenzioso, non crash**: se la chiamata HTTP fallisce,
   `aion-compaction.ts:50-51,68-70` ritorna `undefined` e Pi usa la sua
   sintesi built-in — la conversazione non si rompe. **Ma** questo fallback
   non produce alcun log/segnale visibile: una regressione nella qualità
   della compattazione "AION-aware" potrebbe passare inosservata a lungo.

### 4.3 Circuit breaker (`tool_circuit.py`) e ledger — condiviso o duplicato?

- `tool_offload.py`/`tool_ledger.py` sono **genuinamente condivisi** (stesso
  JSONL, stessa directory), solo iniettati nel prompt con due meccanismi
  diversi: append diretto lato nativo (`turn_context.py:531-542`) vs hook
  evento `pi.on("context")` → HTTP fetch lato Pi (`aion-ledger.ts:17-43`).
  Duplicazione minore (due percorsi per lo stesso dato), non logica di
  business divergente.
- `tool_circuit.py` è **Pi-only**, non condiviso: circuit breaker in-process
  (dict globale `_FAIL_COUNTS`, non persistito) su fallimenti di
  validazione preflight per tool di scrittura (`sandbox_write_workspace_file`,
  `sandbox_edit_workspace_file`, `sandbox_apply_patch`). Esiste perché la
  validazione TypeBox lato client di Pi è più severa di quanto l'LLM produca
  in modo affidabile per JSON grandi/parziali (`aion-bridge.ts:29`) — è una
  patch Pi-specifica per un problema Pi-specifico, **non duplicazione**. Ma
  significa che il path nativo **non ha alcuna protezione equivalente**
  contro loop di retry su errori identici ripetuti.

### 4.4 Punti di forza confermati

- **Resume/riuso sessione**: `ensurePiSession` (`session-factory.ts:36-43`)
  riusa la sessione in-memory tra turni.
- **Cold-start hydration**: se il worker è ripartito e la sessione Pi è vuota,
  `_resolve_pi_prompt_message` (`pi_turn_runner.py:64-91`) antepone un prefix
  STM formattato (cap 12000 char) per continuare in modo coerente dopo un crash.
- **Cleanup turni orfani**: `_abort_stale_pi_session` (`pi_turn_runner.py:164-173`)
  + cancellazione lato server (`server.ts:113-118`) prima di ogni nuovo prompt.
- **Degradazione controllata** su fallimento compattazione (§4.2).
- **Circuit breaker anti-loop** su tool di scrittura (§4.3).

### 4.5 Debolezze/rischi concreti

1. **`AION_LONG_RUN_TOOL_CALLS_MAX` è documentato ma non applicato** —
   calcolato in `long_run_mode.py`/`turn_budget.py`, ma l'enforcement vive
   solo nel loop nativo (`agent_pipeline.py:2647-2653`), mai raggiunto quando
   `agent_mode == "long_run"`. `pi_turn_runner.run_pi_agent_turn` non ha
   **nessun contatore di tool call** — l'unico limite è il timeout dell'intero
   turno (`AION_LONG_RUN_TURN_TIMEOUT`). Un loop di tool runaway è bloccato
   solo dal wall-clock, non da un tetto sul numero di chiamate. Questo è un
   gap funzionale reale, non solo di performance.
2. **SPOF**: sessioni Pi solo in-memory, nessuna replica di stato; un crash
   del worker Node perde tutte le conversazioni attive contemporaneamente.
3. **Circuit breaker non per-sessione**: `_FAIL_COUNTS` è un dict
   process-global, mai resettato automaticamente a fine turno/sessione
   (`reset_session_circuit` risulta chiamato solo dai test).
4. **Fallback di compattazione silenzioso** senza telemetria (§4.2).
5. Autenticazione Node↔Python solo a shared-secret statico
   (`X-Aion-Pi-Secret`) — accettabile su rete privata Docker, ma da segnalare
   come hardening gap se mai esposto.
6. Nessun test per `pi_turn_runner.py` (il loop di orchestrazione/streaming
   stesso) — esistono test per `pi_compaction.py` e `tool_circuit.py`, ma non
   per il consumo del loop NDJSON né per il gap del punto 1.

### 4.6 Gap doc vs implementazione

- `docs/architecture/long-run-pi-mode.md:58-65` descrive la compattazione come
  puramente interna al worker; **non menziona** che `AION_PI_CUSTOM_COMPACTION=1`
  instrada la sintesi reale attraverso il backend Python — dettaglio
  architetturale rilevante mancante.
- Lo stesso doc (linea 44) presenta `AION_LONG_RUN_TOOL_CALLS_MAX=200` come
  guardia attiva — in realtà è codice morto sul path Pi (§4.5.1).
- "SSE contract unchanged" (linea 17) è vero verso il browser, ma la tratta
  Python↔Node è NDJSON-over-HTTP, non SSE — un lettore potrebbe assumere SSE
  end-to-end.

---

## 5. Confronto sintetico dei rischi

| Rischio | AION nativo | Pi long-run |
|---|---|---|
| Perdita permanente di cronologia | 🔴 Sì (DELETE reale, no recovery) | 🟡 Non verificato se tocca il DB AION — da chiarire (vedi §7) |
| Loop infinito di tool falliti | 🔴 Nessuna protezione | 🟢 Circuit breaker (ma non per-sessione) |
| Runaway di tool call (nessun limite) | 🟢 Limite applicato (`agent_pipeline.py:2647-2653`) | 🔴 Limite calcolato ma mai applicato |
| Perdita di sessione per crash processo | 🟢 Stato in DB (history) | 🔴 Stato Pi solo in-memory |
| Complessità operativa / superficie d'attacco | 🟢 Un processo | 🔴 Servizio extra, dipendenza closed-source, secret statico |
| Race condition note | 🟡 `_TURN_RUNTIME_REGISTRY` senza lock | Non riscontrate nell'analisi |

---

## 6. Verdetto esteso

**Investi principalmente sul backend AION nativo.** Ragionamento:

1. **Il vantaggio di velocità del nativo è architetturale, non un dettaglio
   di implementazione.** Pi paga strutturalmente 2+ hop di rete per ogni tool
   call più un pacchetto npm closed-source di cui non controlli il
   comportamento interno. Anche ottimizzando il codice Python/TS di bridging,
   non potrai eliminare questi hop senza cambiare l'architettura stessa (es.
   embedding del worker Pi in-process, che vanifica il motivo per cui esiste
   come servizio separato).

2. **I problemi di "solidità" del nativo che hai osservato sono bug/gap
   puntuali, non limiti architetturali.** La compattazione distruttiva
   (§3.1) è un DELETE reale scelto in un punto preciso del codice
   (`history_bridge.py:798-890`) — sostituibile con soft-delete senza
   toccare il resto della pipeline. Il mancato collegamento ledger/offload
   nel ramo mid-turn (§3.1) è un gap di una singola funzione
   (`_sync_compact_head_tail`). Nessuno dei due richiede un redesign.

3. **L'infrastruttura di offload/ledger che hai appena costruito è già
   condivisa** tra i due backend (§3.2, §4.3) — il lavoro fatto finora non è
   sprecato in nessuno scenario. Ma oggi ne beneficia più il path Pi (che la
   usa in modo più completo nella compattazione, §4.2) che il path nativo
   (dove un ramo intero non la consulta, §3.1). Colmare questo gap nel
   nativo è probabilmente il singolo intervento con il miglior rapporto
   costo/beneficio: prende il path già più veloce e gli dà (quasi) la stessa
   qualità di compattazione che oggi ha solo Pi.

4. **I pattern di solidità propri di Pi sono portabili al nativo con effort
   contenuto**: un circuit breaker equivalente a `tool_circuit.py` per il path
   nativo è un modulo piccolo e già ha un precedente diretto da copiare/adattare.
   Il contrario — rendere Pi veloce quanto il nativo — non è altrettanto
   economico.

5. **Pi introduce un costo operativo strutturale** (servizio Node aggiuntivo,
   dipendenza closed-source non ispezionabile, SPOF in-memory, autenticazione
   a secret statico) che rimane anche se ne migliori l'implementazione lato
   AION. Ha senso mantenerlo per scenari che beneficiano specificamente del
   suo harness (sessioni molto lunghe con necessità di resume/cold-start —
   funzionalità che oggi il nativo non replica), ma non come target primario
   di investimento se l'obiettivo è "il miglior backend generale".

**Sintesi**: converge la solidità di Pi dentro il nativo, non il contrario.

---

## 7. Domande aperte (da chiarire con te prima di pianificare le modifiche)

1. Il testo `[AION COMPACTED]` che citi — è ancora quello che vedi oggi in
   UI, o intendevi il marker `[AION COMPACTION — contesto precedente
   sintetizzato]` trovato nel codice (§2)? Aiuta a capire se il problema
   principale è "il messaggio è brutto/confuso" o "il contenuto sparisce
   davvero" (che restano due problemi distinti, entrambi reali, ma con fix
   diversi).
2. Quando una conversazione gira in **long-run mode**, la compattazione tocca
   anche le tabelle `messages` di AION (stesso DELETE del path nativo) o
   resta confinata al contesto interno del worker Pi? Non sono riuscito a
   confermarlo con certezza dal codice letto — se la risposta è "resta
   interna a Pi", allora Pi non ha affatto il problema di perdita
   permanente di cronologia che ha il nativo, e questo rafforza ulteriormente
   l'urgenza di sistemare `history_bridge.py` lato nativo.
3. Vuoi che la roadmap di modifiche (§8, sotto) sia scritta come task list
   pronta da eseguire in un secondo momento, oppure preferisci prima
   discutere priorità e sequenza?

---

## 8. Modifiche consigliate (nessuna implementata — solo elenco)

### 8.1 Priorità alta — backend nativo (chiude il gap di solidità percepito)

1. **Compattazione non distruttiva**: in
   `src/data/history_bridge.py::persist_stm_compaction` (linee 798-890),
   sostituire `_delete_messages_and_children` con un flag `archived=1` /
   soft-delete, mantenendo i messaggi queryabili (la FTS5 esistente lo
   permette) invece di cancellarli fisicamente. Prerequisito per un futuro
   "espandi cronologia compattata" in UI.
2. **Estendere `_sync_compact_head_tail`** (`turn_compaction.py:701-750`)
   per includere `render_ledger_table()` + `offload_paths_for_session()` nel
   transcript passato all'LLM di sintesi, allineandolo a
   `compact_memory_fallback` (`compaction/policy.py:51-73`).
3. **Portare un circuit breaker equivalente a `tool_circuit.py`** anche nel
   path nativo, dato che lo stesso errore (`tool_args_truncated`,
   `mcp_tool_args.py:183-187`) è generabile da entrambi i path ma oggi solo
   Pi lo intercetta.
4. **Cleanup dei file offloaded alla cancellazione sessione** — hook mancante
   rispetto a quanto promesso in `context-offloading.md:274`.
5. **Fix del fingerprint di config** in `src/runtime/llm_limits.py:65-72`
   (bug confermato dal test fallente `test_pi_fingerprint_changes_with_max_tokens`).
6. **Lock/serializzazione su `_TURN_RUNTIME_REGISTRY`** (`turn_compaction.py:28`)
   per eliminare la race condition riconosciuta nel commento del codice stesso.
7. Migrare `AION_TOOL_OFFLOAD_*`/`AION_TOOL_LEDGER_*` dentro `AionSettings`
   (`src/settings.py`) per coerenza e validazione centralizzata.

### 8.2 Priorità alta — long-run mode (chiude il gap di sicurezza/robustezza)

1. **Applicare il tetto di tool call** (`AION_LONG_RUN_TOOL_CALLS_MAX`)
   dentro il loop NDJSON di `pi_turn_runner.run_pi_agent_turn`, contando gli
   eventi `tool_start`, sullo stesso modello di
   `agent_pipeline.py:2647-2653`. Questo è il gap più critico lato Pi: oggi
   un loop runaway è fermato solo dal timeout di turno.
2. **Rendere osservabile il fallback di compattazione**: quando
   `aion-compaction.ts` fallisce silenziosamente (linee 50-51, 68-70), emettere
   almeno un log/warning (e idealmente un segnale SSE) invece di un
   `undefined` silenzioso.
3. **Scope per-sessione del circuit breaker** (`tool_circuit.py:9`): agganciare
   `reset_session_circuit` alla chiusura/abort della sessione Pi
   (`abortPiSession` in `session-factory.ts` / blocco `finally` in
   `pi_turn_runner.py`), non solo nei test.
4. Valutare persistenza minima dello stato di sessione Pi fuori dal `Map`
   in-memory (`session-factory.ts:34`), per ridurre l'impatto di un riavvio
   del worker oltre al solo prefix STM (che è cappato e lossy su sessioni lunghe).

### 8.3 Priorità media — unificazione tra i due path

1. Consolidare i due meccanismi di iniezione del ledger (append diretto nel
   nativo vs hook evento HTTP in Pi) dietro un'unica interfaccia/contratto
   condiviso, per evitare timing/differenze sottili.
2. Aggiungere un test di integrazione end-to-end (offload → compattazione →
   verifica che il pointer sopravviva nel summary) per il path nativo —
   oggi non coperto.
3. Aggiungere test per `pi_turn_runner.py` (loop di streaming/orchestrazione),
   oggi scoperto.

---

## 9. Fonti

Analisi condotta leggendo per intero (con relativi `git diff`):
`src/runtime/turn_compaction.py`, `src/runtime/compaction/policy.py`,
`src/runtime/llm_limits.py`, `src/runtime/tool_ledger.py`,
`src/runtime/tool_offload.py`, `src/data/history_bridge.py` (sezioni
rilevanti), `src/runtime/turn/turn_context.py`, `src/api/v1/chat.py`,
`src/agent_pipeline.py` (sezioni dispatch/budget), `src/main.py`,
`src/settings.py`, `src/api/internal/pi_tools.py`,
`src/runtime/pi_runtime/{pi_client.py,pi_turn_runner.py,session_config.py,tool_invoke.py,pi_compaction.py,tool_circuit.py}`,
`src/runtime/long_run_mode.py`, `src/runtime/turn_budget.py`,
`services/pi-long-run/src/{server.ts,event-mapper.ts,session-factory.ts}`,
`services/pi-long-run/extensions/{aion-bridge.ts,aion-compaction.ts,aion-ledger.ts}`,
i relativi file di test nuovi/modificati in `src/test/` e
`services/pi-long-run/test/`, `docs/architecture/context-offloading.md`,
`docs/architecture/long-run-pi-mode.md`, `docker-compose.yml` (blocco
`pi-worker`), e i file frontend elencati in `git status`
(`chat-ui/lib/sse/reducer.ts`, `chat-ui/lib/sse/toolOutputParse.ts`,
`chat-ui/components/dock/ToolResultsPanel.tsx`, `ArtifactsPanel.tsx`,
`ContextBudgetBar.tsx`, locales `en.json`/`it.json`).

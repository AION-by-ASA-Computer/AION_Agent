---
title: Piano di solidificazione — Backend AION nativo
sidebar_position: 21
description: Piano operativo step-by-step per chiudere i gap di robustezza del backend AION nativo identificati in aion-vs-longrun-assessment.md.
---

# Piano di solidificazione — Backend AION nativo

> Documento di pianificazione. Nessuna modifica è stata applicata al codice.
> Deriva da `[aion-vs-longrun-assessment.md](./aion-vs-longrun-assessment.md)`
> §3.4 e §8.1. Ogni fase è pensata per essere implementata e testata in
> isolamento, dietro feature flag dove ha senso, senza bloccare le altre.

## Principi guida

1. **Ogni fase è indipendente e reversibile.** Nessuna fase richiede che le
  altre siano già in produzione.
2. **Feature flag first**: ogni comportamento nuovo nasce dietro una env var
  con default che preserva il comportamento attuale, poi si attiva in
   staging prima che in produzione.
3. **Segui i pattern già presenti nel repo** invece di introdurne di nuovi:
  il soft-delete che serve per la compattazione (Fase 1) replica
   esattamente il pattern `archived_at` già usato per `Conversation`
   (`src/api/v1/conversations.py:157-175`) — non è un pattern nuovo da
   inventare.
4. **Ordine consigliato**: Fase 0 → Fase 1 → Fase 2 → Fase 3 → Fase 4 →
  Fase 5 → Fase 6 → Fase 7. Le Fasi 3 e 4 possono essere invertite tra loro
   senza problemi; tutte le altre hanno dipendenze logiche indicate sotto.

---



## Fase 0 — Fix rapidi (nessuna migrazione, rischio minimo)

**Obiettivo**: eliminare i due bug già confermati dai test prima di costruire
altro sopra codice non affidabile.

### 0.1 Fix del fingerprint di config Pi

- **File**: `[src/runtime/llm_limits.py](../../src/runtime/llm_limits.py)`
- **Problema**: `pi_runtime_config_fingerprint()` (linee 65-72) non
cambia quando si modifica `AION_CHAT_MAX_TOKENS` senza settare
esplicitamente `AION_LONG_RUN_MAX_TOKENS`, perché `resolve_chat_max_tokens(long_run=True)`
(linee 11-31) legge solo `settings.long_run_max_tokens` cache via
`get_settings()`.
- **Passi**:
  1. In `resolve_chat_max_tokens`, quando `long_run=True` e
    `settings.long_run_max_tokens is None`, includere comunque il valore
     effettivo di `settings.chat_max_tokens` usato come fallback nella parte
     restituita al chiamante (non solo internamente).
  2. In `pi_runtime_config_fingerprint()` (linee 65-72), calcolare l'hash a
    partire dal **valore risolto finale** (quello che verrebbe realmente
     usato per il turno), non dal solo campo `long_run_max_tokens` grezzo —
     così qualunque input che cambia il risultato finale invalida il fingerprint.
  3. Rilancia `src/test/test_llm_limits.py::test_pi_fingerprint_changes_with_max_tokens`
    e verifica che passi.
- **Verifica**: `python -m pytest src/test/test_llm_limits.py -v`



### 0.2 Migrare le env var offload/ledger in `AionSettings`

- **File**: `[src/settings.py](../../src/settings.py)`
- **Problema**: `AION_TOOL_OFFLOAD_`* e `AION_TOOL_LEDGER_*` sono lette via
`os.getenv` diretto in `tool_offload.py`/`tool_ledger.py`, mentre il resto
della config passa da `AionSettings` (pydantic, `env_prefix="AION_"`,
vedi `settings.py:23-28`).
- **Passi**:
  1. Aggiungere in `AionSettings` (accanto ai campi `tool_calls_max_per_turn`
    etc., `settings.py:71-79`) i nuovi campi tipizzati:
  2. In `tool_offload.py` e `tool_ledger.py`, sostituire le letture dirette
    `os.getenv("AION_TOOL_OFFLOAD_ENABLED", ...)` con
     `get_settings().tool_offload_enabled` (stesso pattern già usato altrove
     nel modulo per altri parametri, se presente — altrimenti importare
     `from src.settings import get_settings` come fanno gli altri moduli
     `runtime/*`).
  3. **Non rimuovere il fallback** `os.getenv` nei test se già usato per
    override rapidi nei test — verificare che i test esistenti
     (`test_tool_offload.py`, `test_tool_ledger.py`) continuino a passare
     mockando `get_settings()` invece delle env var, oppure mantenere
     compatibilità doppia (pydantic legge comunque le stesse env var per
     via del prefix, quindi in pratica il comportamento nei test non
     cambia se già usano `monkeypatch.setenv`).
- **Verifica**: `python -m pytest src/test/test_tool_offload.py src/test/test_tool_ledger.py -v`

---



## Fase 1 — Compattazione non distruttiva (priorità più alta)

**Obiettivo**: eliminare la causa radice del problema segnalato — la
compattazione oggi esegue un `DELETE` SQL reale e irreversibile sui
messaggi. Si sostituisce con soft-delete, seguendo esattamente il pattern
già in uso per `Conversation.archived_at`.

### 1.1 Migrazione schema

- **Nuovo file**: `migrations/versions/<hash>_message_archived_at.py`
(usa `alembic revision -m "message archived at"` per generare l'header
corretto e il `down_revision` puntato all'ultima revision — verifica con
`alembic heads` prima di crearlo, oggi sembra `m5n6o7p015_message_rating_feedback.py`
ma va confermato al momento dell'implementazione).
- **Passi** (modellati esattamente su `migrations/versions/f7a8b9c0d001_mcp_credential_mode.py`,
che già usa il pattern "controlla colonne esistenti prima di aggiungere",
utile per compatibilità SQLite/Postgres):
  ```python
  def upgrade() -> None:
      bind = op.get_bind()
      cols = _columns(bind, "messages")
      if "archived_at" not in cols:
          op.add_column(
              "messages",
              sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
          )
      if "archived_reason" not in cols:
          op.add_column(
              "messages",
              sa.Column("archived_reason", sa.String(32), nullable=True),
          )  # "mid_turn_compaction" | "emergency_compaction" | "stm_prune"
      op.create_index(
          "ix_messages_conversation_archived",
          "messages",
          ["conversation_id", "archived_at"],
      )

  def downgrade() -> None:
      bind = op.get_bind()
      op.drop_index("ix_messages_conversation_archived", table_name="messages")
      cols = _columns(bind, "messages")
      if "archived_reason" in cols:
          op.drop_column("messages", "archived_reason")
      if "archived_at" in cols:
          op.drop_column("messages", "archived_at")
  ```
- **Nota FTS5**: `Message` usa `fts_rowid` come PK autoincrement legata a
un indice FTS5 esterno (vedi `src/data/models.py:112-114`). Verificare in
`src/data/history_bridge.py` come viene sincronizzato l'indice FTS
(probabilmente trigger SQLite o sync manuale) — i messaggi archiviati
**devono restare** nell'indice FTS per continuare a essere trovabili da
ricerca full-text storica, quindi questa migrazione non deve toccare la
logica FTS, solo aggiungere le due colonne.



### 1.2 Modello ORM

- **File**: `[src/data/models.py](../../src/data/models.py)` (linee 110-146)
- **Passi**: aggiungere alla classe `Message`:
  ```python
  archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
  archived_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
  ```



### 1.3 `history_bridge.py` — sostituire il DELETE fisico

- **File**: `[src/data/history_bridge.py](../../src/data/history_bridge.py)`
- **Passi**:
  1. Aggiungere una nuova funzione accanto a `_delete_messages_and_children`
    (linea 64):
  2. **Non rimuovere** `_delete_messages_and_children` — resta utile per
    path espliciti di cancellazione definitiva (es. GDPR / retention
     policy futura), ma **smettere di chiamarla per la compattazione**.
  3. Nei tre punti che oggi chiamano `_delete_messages_and_children` per
    compattazione/pruning (linee 729, 861, 889 — dentro
     `persist_stm_compaction` e la funzione di pruning STM), sostituire la
     chiamata con `_archive_messages_and_children(session, session_id, pruned_ids, reason="mid_turn_compaction")`
     (o `"stm_prune"` a seconda del contesto).
  4. **Rimuovere/adattare** le chiamate a `_cleanup_orphan_steps_and_attachments`
    nei punti dove ora si archivia invece di cancellare: gli step/attachment
     dei messaggi archiviati non sono più "orfani" (il messaggio esiste
     ancora), quindi quella funzione va invocata solo nei path che usano
     ancora il delete fisico.



### 1.4 Filtrare i messaggi archiviati da tutte le letture "attive"

Questo è il passo con più superficie — `history_bridge.py` ha ~10 query
`select(Message)...`. Ogni query che serve a costruire il **contesto attivo
per l'LLM** o la **history mostrata in chat-ui** deve escludere i messaggi
archiviati; le query che servono a **ricerca/audit/FTS** devono continuare a
includerli.

- **Passi**:
  1. Individuare, per ognuna delle occorrenze elencate sotto, se è "contesto
    LLM/chat attivo" (→ aggiungere `.where(Message.archived_at.is_(None))`)
     o "ricerca/audit" (→ lasciare invariata):
    - `history_bridge.py:54` (query generica — verificare uso a valle)
    - `history_bridge.py:105` (join su `conversation_id`)
    - `history_bridge.py:158`
    - `history_bridge.py:521-523` (già ha un filtro `exclude_message_ids`
    esplicito — buon posto per capire il pattern di filtro esistente e
    riusarlo)
    - `history_bridge.py:614`
    - `history_bridge.py:676`
    - `history_bridge.py:734` (`fetch_messages_for_compaction` — **questa
    NON va filtrata**, deve poter rileggere anche messaggi già archiviati
    in compattazioni precedenti se serve costruire un riassunto cumulativo)
  2. In `[src/api/history.py](../../src/api/history.py)` e
    `[src/api/v1/conversations.py](../../src/api/v1/conversations.py)`
     (endpoint `get_conversation_messages`, linea 178 e successive),
     aggiungere un parametro opzionale `include_archived: bool = Query(False)`
     — di default la UI vede solo i messaggi attivi (comportamento identico
     a oggi), ma un endpoint/parametro esplicito permette un futuro
     "espandi cronologia compattata" senza nuove migrazioni.



### 1.5 Nessuna modifica al frontend in questa fase

Il comportamento visibile in chat-ui resta identico (il messaggio di
compattazione con `format_compaction_block()` continua a comparire come
oggi) — questa fase è puramente backend/dati. L'esposizione UI di
"espandi cronologia" è discussa come estensione futura in **Fase 8**
(fuori scope stretto del backend).

### 1.6 Test

- Estendere/creare `src/test/test_history_bridge_compaction.py`:
  - Verifica che dopo `persist_stm_compaction`, i messaggi pruned abbiano
  `archived_at` valorizzato e **non siano stati eliminati dalla tabella**.
  - Verifica che `get_conversation_messages(include_archived=False)` non li
  restituisca, mentre `include_archived=True` sì.
  - Verifica che `fetch_messages_for_compaction` continui a vederli (per
  permettere riassunti cumulativi futuri).

---



## Fase 2 — Collegare ledger/offload al ramo mid-turn sync

**Dipende da**: nessuna (indipendente da Fase 1, ma va fatta prima che
l'offload sia abilitato di default in produzione, altrimenti il gap
descritto in `aion-vs-longrun-assessment.md` §3.1 resta aperto).

- **File**: `[src/runtime/turn_compaction.py](../../src/runtime/turn_compaction.py)`,
funzione `_sync_compact_head_tail` (linee 701-750).
- **Riferimento**: replicare cosa fa già `compact_memory_fallback` in
`[src/runtime/compaction/policy.py](../../src/runtime/compaction/policy.py)`
(linee 44-73) per il path v2.
- **Passi**:
  1. In `_sync_compact_head_tail`, prima di costruire il prompt di sintesi
    per l'LLM, importare e chiamare (solo se abilitati):
  2. Se `tool_ledger_enabled()`, appendere `render_ledger_table(session_id)`
    al transcript passato al summarizer, nello stesso formato/posizione
     usato in `compaction/policy.py:51-73` (blocco `<tool-trace>`).
  3. Se ci sono path offloaded per la sessione, appendere un blocco
    `<offloaded-results>` con `offload_paths_for_session(session_id)`,
     identico a quanto fatto nel path v2 — così il riassunto generato
     mid-turn conserva i pointer ai file offloaded invece di perderli.
  4. Attenzione al **budget di token** del prompt di sintesi: sia
    `render_ledger_table` che l'elenco path offloaded vanno troncati con lo
     stesso criterio già usato in `pi_compaction.py:109` (cap caratteri) per
     non far esplodere il costo della chiamata di sintesi.
- **Test**: nuovo test in `src/test/test_turn_compaction.py` (se non esiste,
crearlo) che: offload un risultato tool grande → forza compattazione
mid-turn sync → verifica che il messaggio di summary risultante contenga
il riferimento al path offloaded.

---



## Fase 3 — Circuit breaker nativo per tool falliti ripetutamente

**Dipende da**: nessuna.

**Obiettivo**: oggi solo il path Pi ha un breaker
(`src/runtime/pi_runtime/tool_circuit.py`) contro loop di retry su errori
identici (`missing_arguments`, `tool_args_truncated`, generati da
`prepare_mcp_tool_arguments` in `src/runtime/mcp_tool_args.py:196` e usati
da entrambi i path). Il path nativo (`src/main.py:306-310`) non ha alcuna
protezione equivalente.

### 3.1 Scelta di design: modulo condiviso, non duplicato

Invece di scrivere un secondo circuit breaker copiato in
`src/runtime/`, **spostare** `tool_circuit.py` da
`src/runtime/pi_runtime/tool_circuit.py` a `src/runtime/tool_circuit.py`
(livello condiviso, come `tool_offload.py`/`tool_ledger.py`), e farlo
usare da entrambi i path. Questo evita la duplicazione futura ed è
coerente con come è già organizzato il resto dell'infrastruttura
offload/ledger (§3.2 di `aion-vs-longrun-assessment.md` la definisce già
"genuinamente condivisa" per gli altri due moduli).

- **Passi**:
  1. `git mv src/runtime/pi_runtime/tool_circuit.py src/runtime/tool_circuit.py`
    (nessuna modifica al contenuto in questo step).
  2. Aggiornare l'unico import esistente in
    `src/runtime/pi_runtime/tool_invoke.py:76-82` (o dove il modulo è
     importato) per puntare al nuovo percorso `src.runtime.tool_circuit`.
  3. In `src/main.py`, subito dopo la chiamata a `prepare_mcp_tool_arguments`
    (linee 306-310), aggiungere lo stesso pattern già usato lato Pi in
     `tool_invoke.py`:
  4. Verificare che `session_id` sia già disponibile in quello scope di
    `src/main.py` (probabile, dato che il tool wrapper opera già per
     sessione) — se non lo è, propagarlo dal chiamante.
  5. Agganciare `reset_session_circuit(session_id)` alla fine di un turno
    nativo completato con successo (dove oggi si fa già cleanup di stato
     per-turno — cercare il punto analogo a `clear_context()` usato lato Pi,
     `pi_turn_runner.py:361`, e replicarlo nel path nativo).
- **Nota**: questo cambiamento risolve *anche* uno dei gap segnalati per Pi
in `aion-vs-longrun-assessment.md` §4.5.3 (reset non per-sessione) **se**
fatto bene — assicurarsi che `reset_session_circuit` venga chiamato in
entrambi i path a fine turno, non solo nel nativo.
- **Test**: spostare/estendere i test esistenti (verificare se
`src/test/test_pi_tool_circuit.py` testa solo import da `pi_runtime` —
aggiornare il path di import) e aggiungere un test nativo che verifichi
che dopo N fallimenti identici (`AION_TOOL_CIRCUIT_BREAKER_MAX`, rinominare
l'env var da `AION_PI_TOOL_CIRCUIT_BREAKER_MAX` a un nome neutro visto che
ora è condivisa — con fallback di compatibilità sul nome vecchio) il tool
wrapper nativo ritorni l'errore `circuit_breaker` invece di ritentare.

---



## Fase 4 — Cleanup file offloaded alla cancellazione sessione

**Dipende da**: nessuna.

- **File**: `[src/api/v1/conversations.py](../../src/api/v1/conversations.py)`,
funzione `delete_conversation` (linee 157-175).
- **Contesto**: oggi questo endpoint fa soft-delete della `Conversation`
(`archived_at`, linee 166-170) e poi rilascia il pool MCP
(`mcp_manager.release_session`, linea 174) — ma non tocca i file offloaded
su disco in `data/sessions/<sid>/derived/tool_results/`, contraddicendo
quanto promesso in `docs/architecture/context-offloading.md:274`.
- **Passi**:
  1. In `src/runtime/tool_offload.py`, aggiungere una funzione pubblica:
    ```python
     def cleanup_session_offloads(session_id: str) -> None:
         """Remove the offloaded tool-result directory and ledger for a session."""
         base = safe_resolve(session_id, "derived/tool_results")
         if base.exists():
             shutil.rmtree(base, ignore_errors=True)
         ledger_path = safe_resolve(session_id, "_ledger.jsonl")
         if ledger_path.exists():
             ledger_path.unlink(missing_ok=True)
    ```
  2. In `delete_conversation` (`conversations.py:157-175`), dopo il rilascio
    MCP, chiamare:
  3. **Decisione da confermare con l'utente**: la cancellazione conversazione
    oggi è soft-delete (`archived_at` su `Conversation`) — se in futuro
     l'utente potrà "ripristinare" una conversazione archiviata, cancellare
     subito i file offloaded rende quel ripristino incompleto (i pointer nel
     summary punterebbero a file non più esistenti). Alternativa più
     prudente: **non cancellare subito**, ma aggiungere un job di pulizia
     periodico (cron/task schedulato) che rimuove `derived/tool_results/`
     solo per conversazioni con `archived_at` più vecchio di N giorni. Vedi
     domanda in fondo al documento.
- **Test**: `src/test/test_tool_offload.py`, nuovo caso che crea file
offloaded finti, chiama `cleanup_session_offloads`, verifica che la
directory sparisca.

---



## Fase 5 — Lock sul registry condiviso mid-turn

**Dipende da**: nessuna, ma va fatta con attenzione dopo Fase 2 (stesso file).

- **File**: `[src/runtime/turn_compaction.py](../../src/runtime/turn_compaction.py)`,
`_TURN_RUNTIME_REGISTRY` (linea 28).
- **Problema riconosciuto nel codice stesso** (commento linee 26-27): il
dict è condiviso tra il task asyncio dello SSE loop (parent) e il task
figlio di `agent.run` (child), mutato da entrambi senza lock.
- **Passi**:
  1. Introdurre un dict parallelo di lock per-sessione:
    ```python
     _TURN_RUNTIME_LOCKS: Dict[str, asyncio.Lock] = {}

     def _get_turn_lock(session_id: str) -> asyncio.Lock:
         lock = _TURN_RUNTIME_LOCKS.get(session_id)
         if lock is None:
             lock = asyncio.Lock()
             _TURN_RUNTIME_LOCKS[session_id] = lock
         return lock
    ```
  2. Individuare **tutti** i punti che leggono/scrivono `rt["live_messages"]`,
    `rt["extra_tokens"]` o altre chiavi mutabili di `_TURN_RUNTIME_REGISTRY[session_id]`
     (grep `_TURN_RUNTIME_REGISTRY\[` e `rt\[` nel file) e avvolgerli con
     `async with _get_turn_lock(session_id):` — attenzione: se alcuni di
     questi accessi sono oggi **sincroni** (non in funzioni `async def`),
     valutare se serve un lock sincrono (`threading.Lock`) invece di
     `asyncio.Lock`, a seconda di dove gira realmente il codice mid-turn
     (thread separato per Haystack `agent.run` sync vs task asyncio) — **da
     verificare con un test di concorrenza mirato prima di scegliere il tipo
     di lock**, non assumere.
  3. Aggiungere cleanup del lock quando la sessione termina (evitare leak
    del dict `_TURN_RUNTIME_LOCKS` su sessioni lunghe/molte sessioni).
- **Test**: test di stress che lancia N task concorrenti che mutano lo
stesso `session_id` e verifica assenza di stati inconsistenti (conteggio
finale di `extra_tokens` corretto rispetto alla somma attesa).

---



## Fase 6 — Osservabilità

**Dipende da**: idealmente dopo Fasi 1-4, per avere qualcosa di significativo
da osservare.

- **Obiettivo**: rendere visibili (log strutturati, non necessariamente una
dashboard) gli eventi chiave che oggi sono silenziosi:
  1. Ogni volta che avviene una compattazione (mid-turn, emergency, fallback),
    loggare: `session_id`, ramo usato, numero messaggi archiviati, token
     prima/dopo, se ledger/offload erano inclusi nel summary.
  2. Ogni volta che il circuit breaker nativo (Fase 3) blocca un retry,
    loggare a livello `warning` con `session_id`/`tool`/`error_code`.
  3. Ogni volta che `cleanup_session_offloads` (Fase 4) rimuove dati,
    loggare quanti byte/file sono stati liberati.
- **File**: aggiungere logging strutturato (`logger = logging.getLogger("aion.turn_compaction")`
già esiste in `turn_compaction.py:22` — riusarlo; crearne uno analogo
`aion.tool_circuit` e `aion.tool_offload` se non già presenti).
- **Nota**: questa fase non richiede nuova infrastruttura (no Prometheus
nuovo) se `docs/architecture/observability.md` descrive già un sistema di
log strutturati esistente — verificare quel documento prima di introdurre
pattern nuovi.

---



## Fase 7 — Test di integrazione end-to-end

**Dipende da**: Fasi 1, 2, 3, 4 completate.

- **Nuovo file**: `src/test/test_native_hardening_integration.py`
- **Scenario da coprire** (un solo test end-to-end che valida l'intera
catena, oltre ai test unitari già elencati per fase):
  1. Sessione con `AION_TOOL_OFFLOAD_ENABLED=1`, `AION_TOOL_LEDGER_ENABLED=1`.
  2. Un tool call produce un risultato grande → viene offloaded.
  3. Si forza una compattazione mid-turn sync (Fase 2 collegata).
  4. Si verifica che: (a) il summary generato referenzia il path offloaded;
    (b) i messaggi originali risultano `archived_at` non-null ma ancora
     presenti in tabella (Fase 1), non cancellati; (c) una successiva query
     "attiva" (`include_archived=False`) non li restituisce.
  5. Si forza un secondo fallimento identico di preflight su un tool di
    scrittura → verifica che il circuit breaker nativo (Fase 3) blocchi il
     terzo tentativo.
  6. Si cancella la conversazione → verifica cleanup offload (Fase 4, o
    verifica che il job periodico sia schedulato se si è scelta
     l'alternativa prudente).

---



## Sequenza di rollout consigliata


| Step | Fase                            | Rischio                      | Flag di attivazione                                                                        |
| ---- | ------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------ |
| 1    | Fase 0 (fix bug)                | Molto basso                  | Nessuno, fix diretto                                                                       |
| 2    | Fase 1 (soft-delete)            | Medio (tocca query multiple) | Nessun flag nuovo: il comportamento osservabile resta identico, cambia solo la persistenza |
| 3    | Fase 2 (ledger in mid-turn)     | Basso                        | Eredita `AION_TOOL_LEDGER_ENABLED`/`AION_TOOL_OFFLOAD_ENABLED` (default on) |
| 4    | Fase 3 (circuit breaker nativo) | Basso                        | Nuovo flag `AION_TOOL_CIRCUIT_BREAKER_ENABLED` (default off finché non validato)           |
| 5    | Fase 4 (cleanup offload)        | Basso                        | Nessun flag — ma decidere subito/differito (vedi domanda sotto)                            |
| 6    | Fase 5 (lock registry)          | Medio (concorrenza)          | Nessun flag, ma deploy su staging con carico concorrente prima di produzione               |
| 7    | Fase 6 (osservabilità)          | Nullo                        | N/A                                                                                        |
| 8    | Fase 7 (test integrazione)      | N/A                          | Gate di CI prima di abilitare i flag sopra in produzione                                   |


Solo dopo che Fasi 0-4 sono in produzione e stabili, valutare se alzare i
default di `AION_TOOL_OFFLOAD_ENABLED`/`AION_TOOL_LEDGER_ENABLED` da `0` a `1`
di default — oggi il piano li lascia opt-in.

---



## Fase 8 — Cronologia completa in chat-ui (implementata)

La chat-ui mostra **tutta** la cronologia (messaggi con `archived_at` inclusi).
Il contesto LLM resta compattato via `history_manager.get_window()` / STM, che
esclude i messaggi archiviati.

- **API chat-ui**: `GET /chat-ui/conversations/{id}/messages` — default
  `include_archived=true`; ogni riga archiviata espone `archived: true` (e
  opzionale `archived_reason`).
- **Client**: `fetchConversationHistory()` invia sempre `include_archived=1`.
- **UI**: etichetta discreta sui messaggi archiviati; modifica messaggio
  disabilitata su righe archiviate.

L'API REST `/v1/conversations/{id}/messages` mantiene `include_archived=false`
di default per i client programmatici.

---



## Domande aperte prima di iniziare l'implementazione

1. **Fase 4**: preferisci cancellazione immediata dei file offloaded alla
  cancellazione conversazione, o job periodico differito (più sicuro se in
   futuro vuoi un "ripristina conversazione")?
2. **Fase 1**: vuoi che i messaggi archiviati restino **per sempre** in
  tabella (solo esclusi dalle query attive), o serve comunque una retention
   policy/hard-delete dopo N giorni per motivi di dimensione DB o compliance?
3. **Fase 3**: sei d'accordo a spostare `tool_circuit.py` da
  `pi_runtime/` a `src/runtime/` (modulo condiviso), o preferisci due
   implementazioni separate per mantenere isolamento tra i due path anche
   a costo di duplicazione minima?
4. Vuoi che proceda a implementare **Fase 0** (i due fix a rischio minimo)
  subito, o preferisci rivedere prima l'intero piano?


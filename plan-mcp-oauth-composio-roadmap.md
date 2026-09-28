# Piano di implementazione — Completamento OAuth2 MCP (Soluzione A) e roadmap Composio

> **Stato**: proposta per il team di sviluppo — da assegnare
> **Origine**: analisi "Composio e l'architettura MCP di AION Agent" (`Analisi_Composio_vs_AION_MCP.docx`)
> **Ultimo aggiornamento**: 2026-07-30

## 0. Correzione rispetto al documento di analisi precedente

Durante la stesura di questo piano è stata fatta una verifica più approfondita del codice rispetto all'analisi iniziale, ed è emerso un punto importante da correggere: **il flusso OAuth2 non è "bloccato a 501" come riportato nel documento di analisi**. Quel dettaglio si riferiva a un endpoint diverso (il gate generale delle credenziali utente, attivabile con `AION_MCP_USER_CREDENTIALS=1`), non allo scambio codice/token.

Lo stato reale, verificato in `src/api/v1/mcp_integrations.py` (1094 righe), è molto più avanzato:

- Flusso OAuth2 **Authorization Code + PKCE (S256)** completo (`_generate_pkce_pair`, righe 583-589).
- **Discovery automatica** del resource server (RFC 9728, `/.well-known/oauth-protected-resource`) e dell'authorization server (RFC 8414, `/.well-known/oauth-authorization-server`) — righe 660-810 circa.
- **Dynamic Client Registration** (RFC 7591) quando il server remoto la supporta — righe 811-850 circa.
- Endpoint `GET /v1/integrations/oauth/start` (avvio flow) e `GET /v1/integrations/oauth/callback` (scambio codice/token, redirect verso chat-ui con esito) — righe 592 e 932.
- Endpoint `GET /v1/integrations/{server_slug}/oauth-status` per interrogare se l'utente è connesso.
- Storage del `refresh_token` ricevuto, come credenziale `OAUTH_REFRESH_TOKEN` (righe 544-551 e 1068-1075).

**Il gap reale, verificato, è più circoscritto e riguarda esclusivamente questi punti**, confermati leggendo `src/runtime/credential_store.py`:

1. **Nessuna rotazione automatica del token**: `get_credential()` (righe 195-229), quando trova una credenziale con `expires_at` nel passato, si limita a **ignorarla e restituire `None`** (riga 213-220, log `"Credenziale scaduta"`). Non viene mai eseguita una chiamata `grant_type=refresh_token` verso il `token_url`. Il `refresh_token` salvato non viene quindi mai utilizzato da nessuna parte del codice (verificato: `grep grant_type` restituisce solo `authorization_code`, mai `refresh_token`).
2. **Zero copertura di test** per l'intero flusso OAuth2: non esiste alcun file `src/test/test_*oauth*.py`. Un flusso con PKCE, discovery RFC 9728/8414 e dynamic client registration, di questa complessità, senza test è un rischio concreto di regressione silenziosa.
3. **Dynamic Client Registration non ha un gate di sicurezza/approvazione**: il codice registra automaticamente un client OAuth su qualunque authorization server che esponga l'endpoint di registrazione, senza intervento dell'amministratore. Da rivedere (vedi Fase 3).
4. **Iniezione header per server `remote-bridge`** basata su parsing di stringa degli argomenti CLI (`_extract_remote_bridge_token_key`, `src/mcp_credential_discovery.py:501-511`) — fragile, come già segnalato nell'analisi.
5. **Stato del flow PKCE tenuto in memoria di processo** (`_oauth_pending`, dizionario globale in `mcp_integrations.py:569`) — coerente con il vincolo `--workers 1` documentato in `CLAUDE.md`, ma va reso esplicito come assunzione architetturale vincolante (non deve mai diventare multi-worker senza spostare questo stato altrove).

Questo piano è quindi **più mirato e a minor sforzo** di quanto stimato nell'analisi iniziale: non si tratta di costruire un flusso OAuth2 da zero, ma di chiudere un gap specifico (refresh automatico), aggiungere test e mettere in sicurezza due punti del flusso esistente.

---

## 1. Obiettivi e non obiettivi

**Obiettivi di questo piano:**
- Rendere il flusso OAuth2 di AION realmente "invisibile" per l'utente finale: nessuna ri-autenticazione manuale finché il `refresh_token` è valido.
- Portare la copertura di test del flusso OAuth2 a un livello accettabile per codice che gestisce credenziali di terzi.
- Chiudere le fragilità puntuali già identificate (dynamic client registration, remote-bridge header injection).
- Eseguire gli altri next step del documento di analisi (catalogo connettori, pattern meta-tool) come attività a priorità inferiore.
- Documentare esplicitamente la valutazione sull'Opzione B (connettore opt-in verso Composio) come epic separata, commerciale, non tecnica.

**Esplicitamente fuori scope:**
- Qualunque integrazione o dipendenza diretta dal backend cloud di Composio come default o requisito.
- Riprogettazione del modello di pooling dei worker MCP (`src/mcp_manager.py`) — è già solido, non va toccato in questo piano.
- Migrazione a un modello multi-worker per il backend FastAPI (resta `--workers 1` per vincolo architetturale documentato).

---

## 2. Fase 1 (Priorità Alta) — Rotazione automatica del refresh token

### 2.1 Contesto

Oggi, quando una credenziale OAuth scade (`expires_at` nel passato), `get_credential()` la ignora silenziosamente e il worker MCP viene avviato senza token valido, con conseguente fallimento delle chiamate al connettore o mancata attivazione del tool. L'utente deve rendersi conto del problema e ripetere manualmente il flusso da "Le mie integrazioni" in chat-ui.

### 2.2 Design proposto

Introdurre una funzione `get_credential_with_refresh()` (o estendere `get_credential()` con un parametro opzionale `auto_refresh: bool = False` da attivare solo nei punti che risolvono credenziali OAuth) che, quando trova una credenziale scaduta con un `OAUTH_REFRESH_TOKEN` associato:

1. Recupera `oauth_config_json` dal `McpServerConfig` del `server_slug` (stesso pattern già usato in `mcp_integrations.py`, es. righe 429-455).
2. Esegue una `POST` al `token_url` con `grant_type=refresh_token`, `refresh_token=<valore decifrato>`, `client_id` (e `client_secret` se presente) — stesso schema HTTP già implementato per l'`authorization_code` grant (righe 456-480 e 990-1010 di `mcp_integrations.py`, da fattorizzare in una funzione condivisa, vedi 2.4).
3. Se la risposta contiene un nuovo `access_token` (ed eventualmente un nuovo `refresh_token`, alcuni provider lo ruotano), salva la nuova credenziale con `set_credential(..., expires_at=...)`, sovrascrivendo `OAUTH_TOKEN` (e `OAUTH_REFRESH_TOKEN` se ricevuto un nuovo valore).
4. Se il refresh fallisce (provider risponde `invalid_grant`, refresh token revocato, ecc.), elimina la credenziale scaduta e registra un evento diagnosticabile (vedi 2.3) invece di fallire silenziosamente.

### 2.3 Dove agganciare il refresh automatico

Due punti di innesco, da valutare entrambi:

- **Lazy, al momento della risoluzione (consigliato come prima iterazione)**: in `resolve_mcp_env_for_user()` (usata da `src/mcp_manager.py` alle righe 428-443, 1252-1254, 1691-1693, 1813-1815), quando la chiave richiesta è `OAUTH_TOKEN` e la credenziale è scaduta ma esiste un `OAUTH_REFRESH_TOKEN`, tentare il refresh prima di restituire l'ambiente al worker. Vantaggio: un solo punto di modifica (`src/runtime/credential_store.py`), copre automaticamente tutti i chiamanti.
- **Proattivo, in background (seconda iterazione, opzionale)**: un task periodico che scandisce `user_mcp_credentials` per credenziali in scadenza entro N minuti e le rinnova preventivamente, per evitare che la prima richiesta dopo la scadenza paghi la latenza del round-trip di refresh. Da valutare solo se il refresh lazy introduce percettibile latenza in produzione.

### 2.4 Refactoring preliminare consigliato

Il codice di scambio token è oggi duplicato quasi identico tra `oauth_callback` (righe ~456-520) e `oauth_callback_redirect` (righe ~996-1075) in `mcp_integrations.py`. Prima di aggiungere il grant `refresh_token`, estrarre una funzione comune `_exchange_token(token_url, payload, client_id, client_secret) -> dict` in un nuovo modulo (proposta: `src/runtime/oauth_token_exchange.py`) usata da:
- `oauth_callback` (grant `authorization_code`)
- `oauth_callback_redirect` (grant `authorization_code`)
- la nuova logica di refresh in `credential_store.py` (grant `refresh_token`)

Questo evita di triplicare la gestione degli errori HTTP (già presente alle righe 501-519) e rende il refresh coerente con il comportamento già validato in produzione per l'authorization code grant.

### 2.5 Task per lo sviluppatore

- [ ] Creare `src/runtime/oauth_token_exchange.py` con `exchange_authorization_code(...)` e `exchange_refresh_token(...)`, estraendo la logica comune da `mcp_integrations.py`.
- [ ] Aggiornare `oauth_callback` e `oauth_callback_redirect` per usare la nuova funzione condivisa (refactor puro, nessun cambio di comportamento — verificare con i test esistenti/nuovi di Fase 2 prima di procedere alla Fase 1 vera e propria).
- [ ] Aggiungere in `src/runtime/credential_store.py` la funzione di refresh automatico e il parametro/variante per attivarlo nella risoluzione delle credenziali OAuth.
- [ ] Gestire la rotazione del `refresh_token` quando il provider ne restituisce uno nuovo (non tutti i provider lo fanno: leggere `token_data.get("refresh_token")` e aggiornare solo se presente, senza cancellare il vecchio se assente).
- [ ] Gestire il caso di refresh fallito: eliminare la credenziale (`delete_credential`), loggare con contesto (`user_id`, `server_slug`, motivo), e assicurarsi che l'utente veda lo stato "disconnesso" in `oauth-status` così da poter ri-autenticarsi dalla UI.
- [ ] Aggiungere un piccolo margine di anticipo alla verifica di scadenza (es. considerare "scaduto" un token che scade entro 60 secondi) per evitare race condition tra verifica ed uso effettivo del token da parte del sottoprocesso MCP.

### 2.6 Criteri di accettazione

- Un utente con un `refresh_token` valido non deve mai vedere una richiesta di ri-autenticazione manuale finché quel refresh token resta valido lato provider.
- Se il refresh fallisce, l'endpoint `oauth-status` deve riflettere `connected: false` entro la richiesta successiva (nessuno stato "zombie" con credenziale scaduta ma non ripulita).
- Nessuna regressione sul flusso `authorization_code` esistente dopo il refactoring di 2.4.

### 2.7 Test da scrivere (vedi anche Fase 2)

- Refresh riuscito: credenziale scaduta + refresh token valido → nuovo `OAUTH_TOKEN` salvato con nuovo `expires_at`.
- Refresh fallito (`invalid_grant`): credenziale eliminata, nessuna eccezione non gestita propagata al chiamante di `resolve_mcp_env_for_user`.
- Provider che non ruota il refresh token: il vecchio `OAUTH_REFRESH_TOKEN` resta valido dopo un refresh riuscito.
- Nessun `OAUTH_REFRESH_TOKEN` presente: comportamento invariato rispetto a oggi (credenziale ignorata, nessun tentativo di refresh).

---

## 3. Fase 2 (Priorità Alta) — Copertura di test per il flusso OAuth2 esistente

### 3.1 Perché prima del refactoring

Il refactoring proposto in 2.4 tocca codice di produzione che gestisce credenziali reali di utenti finali. Va preceduto da una rete di test che catturi il comportamento attuale, altrimenti il refactoring stesso è rischioso.

### 3.2 Task

- [ ] `src/test/test_mcp_oauth_start.py`: verificare `GET /v1/integrations/oauth/start` — generazione corretta di `code_verifier`/`code_challenge`, salvataggio in `_oauth_pending`, redirect all'`authorization_endpoint` con i parametri attesi (`client_id`, `redirect_uri`, `state`, `code_challenge`, `code_challenge_method=S256`).
- [ ] `src/test/test_mcp_oauth_callback.py`: mock del provider OAuth (via `respx`/`httpx` mock, coerente con le librerie già in uso nel progetto) per coprire: scambio codice riuscito, provider che risponde con errore HTTP, provider raggiungibile ma senza `access_token` nel payload, `state` non trovato/scaduto in `_oauth_pending`.
- [ ] `src/test/test_mcp_oauth_discovery.py`: test della discovery RFC 9728/8414 con risposte mockate (metadata trovato, metadata assente, endpoint non conforme) — riusare come riferimento gli scenari già coperti in `test_mcp_credential_discovery.py` per il probing remoto generico.
- [ ] `src/test/test_mcp_oauth_dynamic_registration.py`: registrazione client riuscita, endpoint di registrazione assente, registrazione fallita (deve degradare a "OAuth non configurabile automaticamente", non a crash).
- [ ] `src/test/test_mcp_oauth_refresh.py`: gli scenari descritti in 2.7.
- [ ] Aggiungere un test di integrazione minimale end-to-end (start → callback simulato → oauth-status → refresh) per validare l'intera catena, non solo le singole funzioni.

### 3.3 Criteri di accettazione

- Copertura delle righe aggiunte/modificate in `mcp_integrations.py` e nel nuovo `oauth_token_exchange.py` non inferiore a quella media del resto del modulo `src/runtime/` (verificare con lo strumento di coverage già configurato nel progetto, se presente in CI).

---

## 4. Fase 3 (Priorità Media) — Hardening della Dynamic Client Registration

### 4.1 Problema

`oauth_start` (righe ~811-850 di `mcp_integrations.py`) esegue una registrazione dinamica del client OAuth (RFC 7591) in modo completamente automatico, contro qualunque `registration_endpoint` scoperto, senza approvazione dell'amministratore. Questo significa che AION, per conto dell'utente, crea un'identità OAuth su un servizio terzo senza revisione umana. Non è di per sé una vulnerabilità, ma è un comportamento che un amministratore di sistema dovrebbe poter controllare esplicitamente, specialmente in ambienti regolamentati.

### 4.2 Task

- [ ] Aggiungere un flag di configurazione (es. `AION_MCP_OAUTH_DYNAMIC_REGISTRATION`, default `1` per non rompere il comportamento attuale, disattivabile per i deployment che lo richiedono) che, se disattivato, salta la registrazione dinamica e richiede che `client_id`/`client_secret` siano configurati manualmente dall'amministratore in `oauth_config_json` tramite il wizard.
- [ ] Loggare (audit log esistente, se presente in `src/api/admin.py`) ogni registrazione dinamica avvenuta, con `server_slug`, `registration_endpoint`, timestamp.
- [ ] Aggiungere un'indicazione nella UI di amministrazione (Hub → dettaglio connettore) quando un `client_id` è stato ottenuto tramite registrazione dinamica, distinguendolo da uno inserito manualmente.

---

## 5. Fase 4 (Priorità Media) — Refactor iniezione header remote-bridge

### 5.1 Problema

`_extract_remote_bridge_token_key()` (`src/mcp_credential_discovery.py:501-511`) individua il nome della variabile d'ambiente da iniettare nell'header `Authorization: Bearer ${VAR}` tramite parsing con espressione regolare degli argomenti CLI del server remoto (`--header "Authorization: Bearer ${VAR}"`). Funziona, ma è fragile a cambi di formattazione dell'header o a varianti di sintassi.

### 5.2 Task

- [ ] Introdurre nel registry uno schema esplicito per i server `remote-bridge` (es. campo `auth_header_template` o `auth_env_var` accanto a `command`/`args`), popolato dal wizard invece di essere dedotto a runtime dal parsing degli `args`.
- [ ] Mantenere `_extract_remote_bridge_token_key()` come fallback per i registry esistenti non ancora migrati, con log di deprecazione quando viene usato il fallback.
- [ ] Aggiornare `config/mcp_connector_catalog.yaml` e il wizard (`McpInstallWizard.tsx`) per generare il nuovo campo esplicito per i nuovi connettori remote-bridge.

---

## 6. Fase 5 (Priorità Bassa) — Ampliamento del catalogo connettori

### 6.1 Obiettivo

Ridurre il lavoro manuale nel wizard per i servizi più richiesti, arricchendo `config/mcp_connector_catalog.yaml` con più voci curate (categoria, campi credenziali, `runtime_env_aliases`), ispirandosi alla tassonomia pubblica dei toolkit di terze parti (solo come riferimento concettuale — nessun codice o dato proprietario da riutilizzare).

### 6.2 Task

- [ ] Individuare, con il team prodotto, la lista dei 10-15 servizi più richiesti dai clienti attuali/prospect (CRM, email, calendario, ticketing) non ancora presenti nel catalogo.
- [ ] Per ciascuno: verificare esistenza di un server MCP community-maintained compatibile, oppure valutare lo sviluppo interno.
- [ ] Aggiungere la voce al catalogo con `credential_fields`, `required_env`, `runtime_env_aliases`, seguendo lo schema già in uso (vedi voce `email_imap` come esempio di riferimento).
- [ ] Validare ogni nuova voce con il test esistente `src/test/test_mcp_connector_catalog.py` (estendere se necessario).

Questa fase è **indipendente e disaccoppiabile** dalle Fasi 1-4: può essere lavorata in parallelo da un altro membro del team.

---

## 7. Fase 6 (Priorità Bassa) — Pattern "meta-tool" per la ricerca/esecuzione dinamica dei tool

### 7.1 Obiettivo

Quando un utente ha molti connettori MCP attivi contemporaneamente, il numero di definizioni di tool caricate nel contesto del modello cresce linearmente e può degradare qualità/costo delle risposte. Il pattern (ispirato ai "meta tools" di Composio, ma implementabile internamente senza alcuna dipendenza esterna) consiste nell'esporre un numero ridotto e fisso di meta-tool (es. `search_tools(query)`, `execute_tool(tool_name, arguments)`) che risolvono a runtime quali tool concreti invocare, invece di iniettare staticamente tutte le definizioni.

### 7.2 Task (da trattare come spike/ricerca, non come implementazione diretta)

- [ ] Misurare, sui profili con più connettori attivi in produzione oggi, quanto effettivamente pesa in token il set di tool definitions rispetto al budget di contesto totale — per verificare se il problema è già rilevante o solo potenziale.
- [ ] Se rilevante: progettare l'interfaccia dei meta-tool e il meccanismo di ricerca (ricerca testuale su nome/descrizione dei tool registrati nel `mcp_manager`, senza bisogno di indicizzazione esterna vista la scala contenuta).
- [ ] Valutare l'impatto su Haystack Agent / `src/main.py` (dove i tool vengono oggi registrati come funzioni top-level, vedi `docs/mcp/`).
- [ ] Prototipo dietro feature flag, non da abilitare di default finché non validato su un profilo reale.

---

## 8. Fase 7 (Opzionale, commerciale) — Connettore opt-in verso Composio (Opzione B)

Questa fase **non è un'attività tecnica indipendente**: richiede prima una decisione commerciale/contrattuale (va presentata esplicitamente a ciascun cliente finale, mai attivata come default). Si documenta qui solo la fattibilità tecnica, da riprendere se e quando la decisione commerciale sarà presa.

### 8.1 Fattibilità tecnica (solo se la decisione commerciale è positiva)

- AION supporta già registry entry di tipo `remote`/`remote-bridge`: l'endpoint MCP hospitato di Composio (`session.mcp.url`) potrebbe in teoria essere aggiunto come una voce di questo tipo.
- Da introdurre: un flag esplicito a livello di `tenant` (non globale) che deve essere attivato consapevolmente dall'amministratore del singolo cliente, con testo informativo chiaro nella UI ("le credenziali per questo connettore transitano su un servizio cloud di terze parti, Composio Inc.").
- Da valutare separatamente: costo per-tenant del piano Composio, termini di servizio, e impatto sul contratto con il cliente finale (probabile necessità di un addendum privacy/DPA).

### 8.2 Non fare

- Non implementare questa fase "silenziosamente" come parte delle Fasi 1-6.
- Non usare l'infrastruttura di credenziali cifrate esistente (`user_mcp_credentials`) per questo connettore: le credenziali, in questo caso, non sono comunque mai in possesso di AION (restano su Composio), quindi non c'è nulla da cifrare localmente — va gestito come un caso a parte, chiaramente distinto nella UI.

---

## 9. Sequenza consigliata e stima indicativa

| Fase | Priorità | Dipendenze | Stima indicativa* |
|---|---|---|---|
| 2 — Test del flusso OAuth2 esistente | Alta | Nessuna (da fare per prima) | 3-4 giorni/persona |
| 1 — Rotazione automatica refresh token | Alta | Fase 2 completata | 3-4 giorni/persona |
| 3 — Hardening dynamic client registration | Media | Fase 1 | 1-2 giorni/persona |
| 4 — Refactor header remote-bridge | Media | Nessuna, parallelizzabile | 2 giorni/persona |
| 5 — Ampliamento catalogo connettori | Bassa | Nessuna, parallelizzabile | continuo, a lotti |
| 6 — Spike meta-tool | Bassa | Nessuna | 2-3 giorni/persona (solo lo spike) |
| 7 — Connettore Composio opt-in | Bloccata da decisione commerciale | Decisione prodotto/legale | non stimabile finché non sbloccata |

\* Stime indicative per un singolo sviluppatore con familiarità già acquisita sul codebase; da validare con il team durante il refinement.

---

## 10. Definition of Done complessiva (Fasi 1-4)

- [ ] Nessuna ri-autenticazione manuale richiesta all'utente finché il refresh token resta valido lato provider (verificato manualmente su almeno un provider OAuth reale in staging, es. Google).
- [ ] Suite di test OAuth2 verde in CI, inclusi gli scenari di errore (refresh fallito, discovery assente, registrazione dinamica fallita).
- [ ] Flag `AION_MCP_OAUTH_DYNAMIC_REGISTRATION` documentato in `.env.example` e in `docs/mcp/`.
- [ ] `docs/mcp/` e `docs/api-and-runtime/mcp-integrations-api.md` aggiornati per riflettere lo stato reale del flusso OAuth2 (oggi la documentazione va allineata a quanto scoperto in Sezione 0 di questo piano).
- [ ] Nessuna regressione sui test esistenti (`test_mcp_credential_discovery.py`, `test_mcp_credential_invalidate.py`, `test_mcp_user_isolation.py`, `test_mcp_user_pool.py`).

---

## Appendice — Mappa dei file coinvolti

| File | Coinvolto in |
|---|---|
| `src/api/v1/mcp_integrations.py` | Fasi 1, 2, 3 — endpoint OAuth start/callback/status, dynamic client registration |
| `src/runtime/credential_store.py` | Fase 1 — refresh automatico, logica di scadenza credenziali |
| `src/runtime/oauth_token_exchange.py` *(nuovo)* | Fase 1 — funzioni condivise di scambio token |
| `src/mcp_credential_discovery.py` | Fase 4 — `_extract_remote_bridge_token_key`, discovery OAuth remoto |
| `src/mcp_manager.py` | Fasi 1, 6 — punti di risoluzione credenziali (righe 428-443, 1252-1254, 1691-1693, 1813-1815), registrazione tool |
| `src/data/models.py` | Fasi 1, 3 — `McpServerConfig` (riga 489), `UserMcpCredential` (riga 622) |
| `config/mcp_connector_catalog.yaml` | Fasi 4, 5 |
| `admin-ui/components/McpInstallWizard.tsx` | Fasi 3, 4, 5 |
| `src/test/test_mcp_credential_discovery.py`, `test_mcp_credential_invalidate.py`, `test_mcp_user_isolation.py`, `test_mcp_user_pool.py` | Fase 2 — test di riferimento esistenti da non rompere |
| `docs/mcp/`, `docs/api-and-runtime/mcp-integrations-api.md` | Da aggiornare a chiusura di ogni fase |

---

*Documento di pianificazione tecnica. Riferimento: `Analisi_Composio_vs_AION_MCP.docx` per il confronto completo con Composio e le motivazioni strategiche alla base di questo piano.*

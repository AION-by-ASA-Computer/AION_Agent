# Piano: refresh silenzioso del token OAuth per i server MCP remoti (khub e simili)

## Contesto

L'indagine allegata (`sto-notando-che-quando-ancient-allen.md`) e l'esplorazione
del codice confermano che oggi il refresh OAuth per i server `remote-bridge`
(es. `khub`, gestiti tramite `mcp-remote`) **non funziona in modo silenzioso**:
quando l'access token scade, invece di essere rinnovato in background tramite
il refresh token, l'utente vede una tab del browser aprirsi e chiudersi da
sola (auto-consenso SSO) e la chiamata successiva fallisce con 401.

Causa: AION prova a mantenere sincronizzata la cache locale di `mcp-remote`
(`~/.mcp-auth/mcp-remote-<version>/<hash>_tokens.json`) scrivendola dal proprio
DB (`user_mcp_credentials`), ma questa sincronizzazione è rotta su più fronti
indipendenti:

1. **Directory sbagliata**: `_get_mcp_remote_version()` in
   [`src/runtime/mcp_remote_cache.py`](src/runtime/mcp_remote_cache.py) ha due
   soli percorsi di rilevamento versione, entrambi inesistenti in questo
   deployment → ritorna sempre il fallback `"0.1.38"` → AION scrive in
   `.mcp-auth/mcp-remote-0.1.38/`. Il vero `mcp-remote` in esecuzione è
   risolto in modo non pinnato via `npx -y mcp-remote` (versione reale
   installata: **0.8.6**, confermata su disco), che usa una directory fissa
   `.mcp-auth/mcp-remote-v1/` — completamente diversa. Risultato: mcp-remote
   non trova mai il token seedato da AION.
2. **Hash del file sbagliato per khub**: `_compute_server_url_hash()` calcola
   `md5(server_url)` ignorando gli header, ma l'algoritmo reale di
   `mcp-remote` include anche gli header quando sono passati via `--header`.
   Il registry (`config/mcp_registry.local.yaml`) per `khub` passa ancora
   `--header 'Authorization: Bearer ${...}'`, contraddicendo l'intento
   dichiarato in [`src/mcp_remote_install.py`](src/mcp_remote_install.py)
   ("non passiamo più `--header` per oauth2") — rende il nome file atteso da
   mcp-remote dipendente dal token stesso, quindi il seeding non può mai
   allinearsi in modo stabile.
3. **Nessuna sincronizzazione inversa**: se comunque `mcp-remote` rinnova o
   riautentica per conto suo, il token buono resta solo nella sua cache;
   nessun codice lo rilegge nel DB di AION. Il loop di refresh di AION
   (`_refresh_expiring_oauth_tokens` in
   [`src/mcp_manager.py:861-905`](src/mcp_manager.py)) userà quindi un
   refresh_token vecchio, riceverà 401 dal provider e **cancellerà la
   credenziale** (`credential_store.py:500-507`), peggiorando la situazione.
4. **`expires_in` mancante → falso "non scade mai"**: `_credential_is_expired`
   ([`src/runtime/credential_store.py:278-286`](src/runtime/credential_store.py))
   tratta `expires_at = NULL` come "mai scaduto" anziché "sconosciuto",
   disattivando silenziosamente il refresh proattivo lato AION per quei
   provider.
5. **Nessuna gestione runtime del 401**: `call_tool_pooled`
   ([`src/mcp_manager.py:1603-1629`](src/mcp_manager.py)) intercetta solo i
   timeout; un 401 dal server remoto durante una chiamata tool reale non
   innesca alcun refresh-and-retry, arriva grezzo all'agente/LLM.

**Obiettivo della richiesta utente**: dopo il login SSO iniziale, quando
l'access token scade, AION deve rinnovarlo da solo tramite il refresh token
(senza aprire alcuna tab del browser) e far sì che `mcp-remote` usi il nuovo
token in modo trasparente per l'utente. Solo quando **anche il refresh token**
è scaduto/revocato, l'utente deve rifare il login SSO come la prima volta.

## Approccio

Dato che `mcp-remote` non espone un modo pulito per "iniettare" un token
dall'esterno mentre gira (nessun flag `MCP_REMOTE_CONFIG_DIR` documentato,
nessun hook di refresh esterno), la strategia più robusta è: **far sì che sia
sempre AION, non mcp-remote, a detenere e rinnovare il token**, e **azzerare
completamente l'affidamento su mcp-remote per l'OAuth** — niente cache PKCE
di mcp-remote, niente seeding, niente fallback "Nota A". mcp-remote riceve il
token solo come header (`Authorization: Bearer <token>`) passato allo spawn,
esattamente come già avviene per i provider `api-key`/`basic`, e da quel
momento fa da semplice proxy stdio↔HTTP senza mai gestire OAuth per conto
proprio. Il suo flusso OAuth interattivo integrato per i server
`remote-bridge` con `auth_env_var` OAuth2 non deve mai poter scattare: se
scatta, è un bug da correggere (token mancante/scaduto passato all'header),
non un fallback da rendere più affidabile.

**Un vincolo tecnico importante**: `mcp-remote` legge l'header solo allo
spawn del subprocess — non esiste un modo per aggiornare l'header di un
processo già in esecuzione. Quindi quando AION rinnova un access token (sia
nel refresh proattivo periodico, sia nel retry-on-401), se esiste un worker
`mcp-remote` già in vita per quella credenziale, **quel worker va terminato e
ricreato da zero** con il nuovo token nell'header, riusando la stessa
infrastruttura di restart già presente per la gestione idle/errori
(`restart_worker`/`restart_workers_for_user` in
[`src/mcp_manager.py`](src/mcp_manager.py)). Il restart avviene sempre
*tra* una chiamata tool e la successiva (mai a metà di una richiesta in
corso), quindi non c'è stdio da preservare a metà stream: la sessione MCP si
riconnette in modo trasparente per l'utente, che nota solo una latenza
minima aggiuntiva sulla prima chiamata dopo il refresh.

Quindi il piano ha due parti: (A) eliminare la causa radice tecnica (mismatch
di cache/hash che diventano irrilevanti perché la cache di mcp-remote non
viene più usata affatto, gestione errata di `expires_at`), e (B) aggiungere
refresh proattivo affidabile + kill-and-respawn del worker + retry-on-401 così
che un access token quasi scaduto non causi mai più un fallback interattivo o
un 401 visibile.

## Modifiche pianificate

### 1. Passare a header-based auth per tutti i server OAuth2 `remote-bridge`

- In [`config/mcp_registry.local.yaml`](config/mcp_registry.local.yaml),
  mantenere `--header 'Authorization: Bearer ${AION_USER_KHUB__OAUTH_TOKEN}'`
  (già presente) ma **allineare il codice all'intento**, non il contrario:
  rimuovere/aggiornare il commento fuorviante in `mcp_remote_install.py` e
  smettere di fare affidamento sul seeding della cache di mcp-remote per il
  token (vedi punto 2). L'header resta l'unico canale con cui mcp-remote
  riceve il token.
- Verificare che `resolve_mcp_env_for_user` e la sostituzione
  `${AION_USER_<SLUG>__OAUTH_TOKEN}` in
  [`src/mcp_manager.py`](src/mcp_manager.py) leggano sempre il valore corrente
  dal DB al momento dello spawn del worker (comportamento già presente, da
  confermare in fase di implementazione).

### 2. Disattivare/deprioritizzare il seeding della cache PKCE/OAuth di mcp-remote

- In [`src/runtime/mcp_remote_cache.py`](src/runtime/mcp_remote_cache.py),
  poiché con l'header-based auth mcp-remote non deve più gestire OAuth in
  autonomia, il seeding di `_tokens.json`/`_client_info.json` diventa
  superfluo per i server con `auth_env_var` (OAuth2). Semplificare o rimuovere
  questa strada per evitare il rischio "hash sbagliato" e la falsa sensazione
  di sincronizzazione. Se si preferisce mantenerla come rete di sicurezza,
  correggere comunque il calcolo della versione/hash (vedi Nota A), ma la
  soluzione primaria resta l'header.

### 3. Correggere `_credential_is_expired` per `expires_at = NULL`

- In [`src/runtime/credential_store.py:278-286`](src/runtime/credential_store.py),
  trattare `expires_at` mancante come "sconosciuto → considera scaduto se
  oltre un TTL di sicurezza" (es. forzare un refresh proattivo periodico anche
  senza `expires_in` dal provider), invece di "non scade mai". Questo
  garantisce che il loop di refresh di AION non ignori silenziosamente i
  provider che non restituiscono `expires_in`.

### 4. Estendere `_refresh_expiring_oauth_tokens` a tutte le credenziali OAuth nel DB, non solo ai worker in pool

- In [`src/mcp_manager.py:861-905`](src/mcp_manager.py), iterare le credenziali
  OAuth in `user_mcp_credentials` (non solo le chiavi presenti in
  `self._pool`), così un worker idle-evicted resta comunque coperto dal
  refresh proattivo periodico. Quando un token viene rinnovato per un server
  senza worker attivo, non serve fare nulla di più: al prossimo spawn il
  worker leggerà il token fresco dal DB (grazie al punto 1).

### 5. Rendere `refresh_oauth_access_token` più tollerante ai 401 transitori

- In [`src/runtime/credential_store.py:500-507`](src/runtime/credential_store.py),
  distinguere `invalid_grant` (revoca reale del refresh token → qui sì va
  cancellata la credenziale e richiesto un nuovo login) da altri errori
  HTTP/transitori (timeout, 5xx, rate limit) che non devono cancellare il
  refresh token esistente. Solo `invalid_grant` (o equivalente esplicito del
  provider) deve far scattare "l'utente deve rifare il login".

### 6. Retry-on-401 in `call_tool_pooled`

- In [`src/mcp_manager.py:1603-1629`](src/mcp_manager.py), quando una chiamata
  tool fallisce con 401/errore di autenticazione dal server remoto, tentare
  un refresh forzato del token (bypassando il buffer di scadenza), fare
  `restart_worker`/`restart_workers_for_user` e ritentare la chiamata una
  volta sola prima di propagare l'errore. Questo copre il caso limite in cui
  il refresh proattivo non è ancora scattato.

### 7. Comportamento a refresh token scaduto/revocato

- Quando `refresh_oauth_access_token` riceve `invalid_grant` (o il refresh
  token stesso risulta assente/scaduto oltre soglia), la credenziale va
  eliminata dal DB (comportamento già presente, da preservare solo per questo
  caso specifico — vedi punto 5) cosicché la prossima chiamata tool fallisca
  in modo esplicito e l'agente/UI possano segnalare "serve un nuovo login" e
  reindirizzare al flusso `/integrations/oauth/start` esistente
  ([`src/api/v1/mcp_integrations.py`](src/api/v1/mcp_integrations.py)) — nessuna
  nuova UI da costruire, solo assicurarsi che l'errore propagato sia
  distinguibile (es. codice/messaggio dedicato) così il chat-ui può mostrare
  un CTA di re-login invece di un errore tool generico.

### Nota A — se si vuole mantenere anche il fallback di cache mcp-remote

Se in fase di implementazione si preferisce non fidarsi al 100% dell'header
(es. compatibilità con futuri server MCP che richiedono OAuth "nativo" senza
header), va comunque risolto il mismatch di directory: rilevare la versione
reale di `mcp-remote` risolta da `npx`/vendored a runtime (non hardcoded), e
verificare il nome cartella reale usato da quella versione (es.
`mcp-remote-v1` fisso invece che version-named) prima di scrivere i file di
seed. Questa nota è un ripiego, non il percorso primario del piano.

## File coinvolti

- [`src/runtime/credential_store.py`](src/runtime/credential_store.py) — fix
  `_credential_is_expired`, `refresh_oauth_access_token` (invalid_grant vs
  transitorio).
- [`src/mcp_manager.py`](src/mcp_manager.py) — `_refresh_expiring_oauth_tokens`
  esteso a tutte le credenziali DB, retry-on-401 in `call_tool_pooled`.
- [`src/runtime/mcp_remote_cache.py`](src/runtime/mcp_remote_cache.py) —
  semplificare/rimuovere seeding per server OAuth2 header-based, o correggere
  se mantenuto come fallback (Nota A).
- [`src/mcp_remote_install.py`](src/mcp_remote_install.py) — allineare
  commenti/logica all'uso effettivo dell'header per OAuth2.
- [`config/mcp_registry.local.yaml`](config/mcp_registry.local.yaml) —
  verificare che tutti i server OAuth2 (`khub` incluso) usino consistentemente
  l'header per l'auth.
- [`src/api/v1/mcp_integrations.py`](src/api/v1/mcp_integrations.py) — nessuna
  modifica strutturale, solo eventualmente un codice di errore dedicato per
  "serve nuovo login" da propagare al client.

## Verifica end-to-end

1. Login SSO iniziale su `khub`, confermare che il token venga salvato in
   `user_mcp_credentials` e che una chiamata tool funzioni.
2. Forzare artificialmente la scadenza dell'access token (es. impostare
   `expires_at` nel passato via DB, o abbassare
   `AION_OAUTH_TOKEN_EXPIRY_BUFFER_SECONDS`/`AION_MCP_OAUTH_REFRESH_AHEAD_SEC`
   per il test) e osservare nei log che `_refresh_expiring_oauth_tokens` (o il
   retry-on-401) rinnova il token **senza** alcuna apertura di browser/tab.
3. Verificare che la chiamata tool successiva funzioni con il nuovo token,
   senza 401.
4. Revocare manualmente il refresh token lato provider (o simulare
   `invalid_grant`) e verificare che AION cancelli la credenziale e che la
   chiamata tool fallisca con un messaggio chiaro che richiede un nuovo login,
   senza loop infiniti di refresh.
5. Testare il caso worker idle-evicted (attendere oltre
   `AION_MCP_POOL_IDLE_SEC` o abbassarlo per il test) e confermare che il
   refresh proattivo copra comunque quella credenziale.

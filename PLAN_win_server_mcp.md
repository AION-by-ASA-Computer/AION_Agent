# Piano: server MCP `smb_files` (file server Windows con credenziali per utente)

## Context

Vogliamo che l'agent AION legga e scriva i file dei Windows Server aziendali (share SMB sulla LAN)
**con le credenziali Windows del singolo utente**, così valgono le ACL NTFS e l'audit di Windows mostra
l'utente reale. Ogni utente inserisce `DOMINIO\utente` + password da chat-ui; l'admin configura una volta
per tenant il file server e le share consentite da admin-ui.

Decisioni prese con l'utente:
- **v1 lettura + scrittura**, ma **niente cancellazione** (SMB non ha cestino). Scritture: crea/aggiorna file
  (no overwrite salvo flag esplicito), crea cartelle, carica dalla sessione, rinomina/sposta nella stessa share.
- **Server e share configurati dall'admin** in una pagina admin-ui (DB per tenant, come SMTP).
- **Auth**: NTLM in v1 (smbprotocol, zero config); Kerberos predisposto ma rimandato.
- **File non testuali**: sia estrazione testo (PDF/DOCX/XLSX/CSV/txt) sia copia nella workspace di sessione
  (per OCR / sandbox).

Gran parte dell'infrastruttura esiste già (pattern del connettore `mssql`): store credenziali AES-256-GCM
(`src/runtime/credential_store.py`), placeholder `${AION_USER_<SLUG>__<KEY>}` risolti allo spawn
(`resolve_mcp_env_for_user`, `src/mcp_manager.py:600-640`), form chat-ui (`CredentialConfigDialog.tsx`),
invalidazione worker al salvataggio (`src/runtime/mcp_credential_invalidate.py` →
`restart_workers_for_user`). Manca il server MCP, la configurazione admin e qualche indurimento.

## Vincoli emersi dall'esplorazione (da rispettare)

- I file tracciati stanno in **`mcp_servers_std/`** e **`config_std/`** (`mcp_servers/` e `config/` sono
  gitignored e popolati da `scripts/sync_mcp_servers.py` / `scripts/sync_config.py`).
- Il processo MCP **viene avviato anche con credenziali vuote o mock** (probe: `generate_probe_mock_value`)
  → startup e `list_tools` **senza I/O di rete**; connessione SMB lazy dentro ogni tool; schema dei tool
  identico a prescindere dalle credenziali (la cache `list_tools` è per utente/registry fingerprint).
- La DB row `mcp_server_configs` deve risultare `credential_mode=per_user` (altrimenti fallback a
  credenziali `org_shared`): è inferito dai placeholder `${AION_USER_*}` nel registry env.
- Chiave utente da chiamare **`SMB_USERNAME`** (non `SMB_USER`): così il dialog la mette tra le
  "Credenziali di Accesso" e non in "Parametri Avanzati" (`chat-ui/lib/integrations/field-labels.ts`).
- Oggi `GET /v1/integrations/credentials/{slug}/{key}` **restituisce la password in chiaro** (icona occhio):
  inaccettabile per una password di dominio → va reso write-only per questo connettore.
- Nessun segnale "credenziali non valide" verso la UI per errori a runtime: il canale v1 è il messaggio
  d'errore del tool (`isError`) con istruzioni chiare.
- Errori dei tool: restituire `json.dumps({"ok": False, "error": "<code>", "message": ...})`
  (stile `ocr_mcp`/`stt_mcp`), non sollevare eccezioni.

## Architettura

```
chat-ui (Le mie integrazioni)            admin-ui (Impostazioni → File server)
  SMB_USERNAME / SMB_PASSWORD              host, porta, dominio default, share [+ read_only], limiti
        │ POST /v1/integrations/credentials        │ GET/PUT /admin/smb, POST /admin/smb/test
        ▼                                          ▼
 user_mcp_credentials (AES-GCM)             smb_settings (1 riga per tenant)
        │ env allo spawn                           │ letta dal server MCP (cache TTL 30s)
        └──────────────► mcp_servers_std/smb_files/server.py (FastMCP, sottile)
                               └─► src/tools/smb_files/* (logica testabile) ─► smbprotocol ─► \\server\share (TCP 445)
```

Il server MCP è first-party: eredita l'env del backend (incluso `AION_DB_URL`) e legge `smb_settings`
per `AION_CURRENT_TENANT_ID` (stesso pattern di tenant di `mcp_servers_std/query_memory/server.py:18`).
Niente da iniettare nello spawn per la config admin; un salvataggio admin vale entro il TTL della cache.

## Fasi di implementazione

### Fase 0 — Ambiente di sviluppo
- `docker-compose.dev.yml`: servizio Samba opzionale (compose `profiles: ["smb"]`) con 2 utenti di test e
  2 share (`Documenti` rw, `Archivio` ro), porta host **1445** (su macOS la 445 può essere occupata dalla
  condivisione file di sistema). Scegliere un'immagine mantenuta (es. `ghcr.io/servercontainers/samba`,
  verificare al momento) con versione fissata.
- `requirements.txt`: aggiungere `smbprotocol` (versione fissata). Nessuna modifica al Dockerfile
  (`docker/Dockerfile.backend:43-49` installa già `requirements.txt`).

### Fase 1 — Logica core in `src/tools/smb_files/` (testabile senza MCP)
Ogni file con header docstring (CLAUDE.md "Code Comments").
- `settings_store.py` — carica/salva `SmbSettings` per tenant, cache TTL 30s + `invalidate_cache(tenant)`;
  ricalca `src/notifications/smtp_settings.py` (`_load_row`, `get_*_public`, `upsert_*`, `record_test_result`).
- `paths.py` — parsing/normalizzazione percorsi: accetta `Share/sub/file.ext` o `\\host\Share\...`;
  rifiuta `..`, share non in allowlist, share amministrative (`C$`, `ADMIN$`, `IPC$`, qualunque `*$`),
  host diverso da quello configurato. Restituisce UNC canonico + flag `read_only` della share.
- `credentials.py` — legge `SMB_USERNAME`/`SMB_PASSWORD` dall'env; normalizza `DOMINIO\utente`,
  `utente@dominio`, o `utente` + dominio di default; errore `credentials_missing` se vuoti/mock.
- `auth_guard.py` — **protezione da blocco account AD**: al primo errore di logon
  (`STATUS_LOGON_FAILURE`, `STATUS_ACCOUNT_LOCKED_OUT`, `STATUS_PASSWORD_EXPIRED`,
  `STATUS_PASSWORD_MUST_CHANGE`, `STATUS_ACCOUNT_DISABLED`) scrive un marker nella HOME isolata per
  utente (`data/users/<uid>/mcp_home`, già impostata da `_apply_mcp_home_isolation`) con un
  fingerprint HMAC (salt casuale nel file) di utente+password e il motivo. Prima di ogni connessione,
  se il fingerprint corrisponde alle credenziali correnti → errore immediato **senza contattare il
  server**. Credenziali aggiornate dall'utente ⇒ fingerprint diverso ⇒ si riprova. Per
  `ACCOUNT_LOCKED_OUT` il blocco scade dopo una finestra configurabile (default 30 min). Condiviso fra
  processi dello stesso utente (più chat aperte).
- `client.py` — wrapper `smbclient` (smbprotocol): `register_session(host, port, username, password,
  auth_protocol="ntlm", require_encryption=settings.require_encryption)` lazy, timeout di connessione,
  mappatura eccezioni → codici (`auth_failed`, `account_locked`, `password_expired`, `access_denied`,
  `not_found`, `already_exists`, `share_read_only`, `too_large`, `timeout`, `unreachable`).
  `auth_protocol` letto dai settings (`ntlm` | `negotiate`) per predisporre Kerberos.
- `extract.py` — estrazione testo da bytes: riusa `src/doc_processor.py:10 extract_text_from_bytes`
  (PDF/CSV/txt/md/json) e **aggiunge lì** i rami DOCX (`python-docx`) e XLSX (`openpyxl`, già in
  `requirements.txt`) così ne beneficia anche il resto del sistema. Troncamento a `max_chars` con
  `offset_chars` per paginare; PDF senza testo / immagini → hint "usa `smb_copy_to_session` e poi OCR".
- `ops.py` — operazioni: `list_shares`, `list_dir`, `stat`, `search` (walk limitato: profondità,
  numero risultati, budget di tempo), `read_file`, `copy_to_session`, `write_text`,
  `upload_from_session`, `mkdir`, `move` (solo stessa share: senza delete non si può spostare tra share).
  Tutte le scritture: verifica `read_only` della share, `overwrite=False` di default
  (`already_exists` se il file c'è), limite dimensione, log strutturato (utente, op, percorso — mai
  contenuti né password).

### Fase 2 — Server MCP e registrazione
- `mcp_servers_std/smb_files/server.py` — FastMCP sottile sul modello di
  `mcp_servers_std/geocoding/server.py` (`sys.path` sul repo root, `mcp.run()`), docstring tool in
  inglese. Tool:
  - lettura: `smb_list_shares`, `smb_list_dir`, `smb_stat`, `smb_search`, `smb_read_file`,
    `smb_copy_to_session`
  - scrittura: `smb_write_text`, `smb_upload_from_session`, `smb_mkdir`, `smb_move`
  Le descrizioni dei tool di scrittura dicono esplicitamente di usarli solo su richiesta esplicita
  dell'utente e di chiedere conferma prima di `overwrite=True`.
- Workspace di sessione (`smb_copy_to_session`, `smb_upload_from_session`): riusare
  `src.session_workspace` (`ensure_session_dirs`, `safe_resolve`) + `AION_CHAT_SESSION_ID`, come
  `ocr_mcp`; aggiungere `"smb_files"` a `_DEFAULT_SESSION_SCOPED_SERVERS` (`src/mcp_manager.py:82`).
  Verificare in `_resolve_pool_key` (`src/mcp_manager.py:1582`) che un server session-scoped con
  `${AION_USER_*}` riceva comunque le credenziali dell'utente della sessione.
- `config_std/mcp_registry.yaml` — nuova voce (pattern `mssql`, ~riga 104):
  ```yaml
  smb_files:
    command: python
    args: [-u, smb_files/server.py]
    description: File server Windows (share SMB) con le credenziali dell'utente
    aion_connector_id: smb_files
    env:
      SMB_USERNAME: ${AION_USER_SMB_FILES__SMB_USERNAME}
      SMB_PASSWORD: ${AION_USER_SMB_FILES__SMB_PASSWORD}
  ```
- `config_std/mcp_connector_catalog.yaml` — voce `smb_files` (pattern `mssql`, ~riga 425):
  `default_credential_mode: per_user`, `credential_fields` con label italiane senza `_`
  (es. "Utente Windows (es. DOMINIO\\mario.rossi)", "Password Windows") e `description` che spiega
  di non scrivere mai la password in chat; `secret: true` + `write_only: true` sulla password.
- Non aggiungerlo ai profili di default: l'admin lo abilita (Hub + `mcp_servers:` del profilo).

### Fase 3 — Configurazione admin (DB per tenant)
- `src/data/models.py` — modello `SmbSettings` (`smb_settings`, PK `tenant_id`, come `SmtpSettings`
  a riga ~1177): `enabled`, `host`, `port` (445), `default_domain`, `shares_json`
  (`[{name, read_only, label}]`), `auth_protocol` (`ntlm`|`negotiate`), `require_encryption`,
  `max_read_mb`, `max_write_mb`, `last_test_at`, `last_test_error`. Nessun segreto.
- `migrations/versions/` — nuova revision Alembic (head da `alembic heads`).
- `src/api/admin_smb.py` — router `/admin/smb` ricalcando `src/api/admin_smtp.py`:
  `GET ""`, `PUT ""` (con `record_admin_action` per l'audit e `invalidate_cache`), `POST /test`
  (connessione + negotiate; credenziali opzionali nel body **solo** per il test, mai salvate né
  loggate). Su `PUT` con `enabled` sincronizzare `McpServerConfig.is_enabled_for_users` di
  `smb_files`. Montare il router in `src/api/main.py` accanto a `admin_smtp`.
- `admin-ui/components/settings/SmbSection.tsx` + registrazione in `admin-ui/app/settings/page.tsx`
  (pattern `SmtpSection`), editor share con toggle "sola lettura", bottone "Testa connessione";
  stringhe nei file i18n di admin-ui.

### Fase 4 — Indurimento credenziali
- Supporto `write_only` nei `credential_fields`: copiarlo in `credential_schema_from_connector`
  (`src/mcp_integration_sync.py:114-180`), esporlo in `integration_row_to_public_dict`
  (`src/runtime/mcp_integration_helpers.py`), e in `GET /credentials/{slug}/{key}`
  (`src/api/v1/mcp_integrations.py:407`) rispondere 403 `secret_write_only` per quei campi.
- chat-ui: `CredentialField.write_only` in `components/integrations/types.ts`; in
  `CredentialConfigDialog.tsx` nascondere il toggle "occhio" per quei campi (riga ~738).
- Il display hint dello username resta leggibile (utile all'utente), la password solo `****`.

### Fase 4b — Più file server per tenant
- Decisioni: server in domini/account diversi → **set di credenziali** per server (`DEFAULT` usa
  `SMB_USERNAME`/`SMB_PASSWORD`, gli altri `SMB_USERNAME__<SET>`/`SMB_PASSWORD__<SET>`, una coppia
  per set, non per server); visibilità **solo ACL NTFS** (chi ha il connettore vede tutti i server
  abilitati); percorsi sempre `alias/Share/percorso` (UNC accettato se l'host è configurato).
- Dati: `smb_settings` tiene solo i globali (`enabled`, limiti, `lockout_minutes`); nuova tabella
  `smb_servers` (alias e host unici per tenant, `credential_set`, share, protocollo, cifratura,
  `enabled`, esito test). Migration `f3a4b5c034`: la riga esistente diventa un server (alias dalla
  prima etichetta DNS, set `DEFAULT`).
- Core: `paths.resolve_path` → `server_not_allowed`; `load_credentials(server, env)`; `auth_guard`
  con un marker per set; `move` solo stesso server e share; `list_shares` raggruppato per server.
- Credenziali extra al processo: placeholder jolly `${AION_USER_<SLUG>__*}` (JSON di tutte le
  credenziali dell'utente per lo slug) in `SMB_EXTRA_CREDENTIALS`; mock nel probe, ignorato da
  discovery e dal gating dello spawn.
- Campi dinamici in chat-ui (`src/runtime/dynamic_credential_fields.py`): una coppia facoltativa per
  set extra, password `write_only`, chiavi ammesse solo `SMB_(USERNAME|PASSWORD)(__<SET>)?`.
- Admin API: `/admin/smb` (globali) + `/admin/smb/servers[/{id}[/test]]`; invariante: a connettore
  abilitato serve un server abilitato con share e set `DEFAULT`. Admin-ui: blocco Generale + una
  scheda per server (`SmbServerCard.tsx`).
- Dev: secondo Samba `samba2` (profilo `smb`, porta host 1446, utente `carla`).

### Fase 5 — Documentazione
- `docs/mcp/smb-files.md` (frontmatter `title`, `sidebar_position`, `description`): architettura,
  server multipli e set di credenziali, setup admin, setup utente, rete (TCP 445, DNS interno,
  `dns:` in compose), blocco account, NTLM vs Kerberos (roadmap), sicurezza (no delete, write-only
  password, prompt injection dai file).
- Aggiornare `docs/mcp/user-isolation-and-credentials.md` (campo `write_only`) e aggiungere una
  breve sezione in `CLAUDE.md` stile "WhatsApp/Telegram channel".

## Fuori scope v1 (roadmap)
Kerberos (librerie krb5/gssapi nell'immagine + config realm), cancellazione file, allowlist dei
server per utente/gruppo (oggi solo ACL NTFS), enumerazione automatica delle share, badge "credenziali non valide" in chat-ui
(`record_mcp_load_error` dal path dei tool), DFS namespace.

## Verifica

1. **Unit test** (`src/test/test_smb_files_*.py`, ognuno con docstring dello scenario), smbclient mockato:
   normalizzazione percorsi e rifiuto di `..`/share `$`/host estranei; normalizzazione username e
   dominio di default; auth guard (blocco dopo logon failure, sblocco con credenziali nuove, scadenza
   lockout); share read-only → `share_read_only`; `overwrite=False` → `already_exists`; limiti
   dimensione; estrazione DOCX/XLSX/PDF; credenziali vuote/mock → `credentials_missing` senza rete;
   endpoint admin GET/PUT/test (pattern `src/test/test_smtp_settings.py`); 403 `secret_write_only`.
   ```bash
   python -m pytest src/test/ -k "smb" -v
   ```
2. **Test di integrazione** contro il container Samba (skip se `SMB_TEST_HOST` non è impostato):
   lettura, scrittura, mkdir, move, utente senza permessi → `access_denied`, password errata → un solo
   tentativo verso il server poi blocco locale.
3. **End-to-end**: `docker compose -f docker-compose.dev.yml --profile smb up`, backend + chat-ui
   (con `AION_MCP_USER_CREDENTIALS=1`); in admin-ui configurare host `samba`/porta 445 e le share,
   "Testa connessione"; abilitare `smb_files` nel Hub e in un profilo; in chat-ui inserire le
   credenziali dell'utente di test; chiedere all'agent di elencare una cartella, leggere un DOCX,
   creare un file in `Documenti`, tentare di scrivere in `Archivio` (deve rifiutare); verificare che
   l'occhio sulla password non mostri il valore e che l'admin probe del Hub non crashi con valori mock.
4. Regressione: `python -m pytest src/test/test_mcp_connector_catalog.py src/test/test_mcp_integration_sync.py src/test/test_credential_store.py -v`
   e `cd chat-ui && npm run lint`, `cd admin-ui && npm run lint`.

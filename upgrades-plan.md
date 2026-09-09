# Piano: script di upgrade GHCR (`install.sh upgrade`) + notifica nuova versione

## Contesto

`scripts/install.sh` implementa già l'installazione one-shot via
`curl .../install.sh | bash`: scarica 5 file (`docker-compose.ghcr.yml`,
`docker/Caddyfile`, `scripts/apply_optimal_aion_env.py`,
`scripts/env_tuning_profiles.py`, `.env.example`), genera `.env` e fa
`docker compose -f docker-compose.ghcr.yml pull && up -d --no-build`.

Non esiste oggi nessun percorso di **upgrade** compatibile con questo modello
di deploy. La famiglia `upgrade-aion.sh` → `upgrade_core.py` (2063 righe) è
pensata solo per il modello *build-from-source* (repo clonata,
`docker-compose.yml`, `docker compose build --pull`): non contiene alcun
riferimento a GHCR (verificato via grep sull'intero repo) e farebbe un
rebuild locale impossibile in una directory che ha solo i 5 file scaricati
da `install.sh`, senza sorgenti.

Altri elementi rilevanti già confermati:
- `.aion-install.json`, scritto da `install.sh`, non viene mai riletto da
  nessuno script: non è una fonte affidabile della versione installata.
- `AION_VERSION` dentro `.env` è invece l'indicatore reale e vivo della
  versione: è il tag immagine che `docker-compose.ghcr.yml` legge
  (`${AION_VERSION:-latest}`) per tutti e 4 i servizi GHCR.
- Le migrazioni Alembic partono automaticamente all'avvio del backend
  (`src/data/migrations.py:run_migrations()`, chiamato da
  `src/api/main.py:226,235`): un upgrade GHCR non deve invocare Alembic a
  mano, basta `pull && up -d` sul nuovo tag.
- `scripts/aion_backup.py` è un backup tar.gz riusabile as-is (db, config,
  plugin, deep_research + manifest.json).
- Non esiste alcun meccanismo di "nuova versione disponibile" in
  `src/api`, `admin-ui/src`, `chat-ui/src` (grep esaustivo, zero risultati).

**Decisioni già prese con l'utente:**
1. L'upgrade GHCR va implementato come **nuova modalità/parametro dentro
   `scripts/install.sh`** (non un flag `--ghcr` in `upgrade_core.py`, non
   un terzo script separato) — coerente con l'intento originale
   `raw.../install.sh` + parametro `upgrade`.
2. Lo scope include anche un **meccanismo di controllo versione**: endpoint
   backend che interroga le GitHub Releases + notifica in admin-ui (e
   chat-ui), mai upgrade automatico — coerente con la filosofia del PDF
   originale (AION gira come servizio always-on, downtime va sempre deciso
   manualmente).

## Approccio

### 1. Nuova modalità `upgrade` in `scripts/install.sh`

Invocazione: sottocomando posizionale, es.
`curl -fsSL .../install.sh | bash -s -- upgrade [--version X.Y.Z] [--yes]`
(coerente con l'uso attuale di `install.sh --version X.Y.Z` per il deploy
pinned, riusando lo stesso parsing di flag già presente nello script).

Flusso della modalità `upgrade`, eseguita nella directory di installazione
esistente (dove già vivono `.env`, `docker-compose.ghcr.yml`, `config/`,
`data/`):

1. **Precondizioni**: verifica che `.env` e `docker-compose.ghcr.yml`
   esistano già in questa directory (altrimenti errore: "nessuna
   installazione trovata, usare `install.sh` senza `upgrade`").
2. **Versione corrente**: legge `AION_VERSION` da `.env` (fonte
   autoritativa, non `.aion-install.json`).
3. **Elenco versioni pubblicate**: interroga
   `https://api.github.com/repos/AION-by-ASA-Computer/AION_Agent/releases`
   (lista completa, non solo `/latest`), la ordina per semver crescente.
   Questa lista è l'unica fonte di verità per "qual è la versione
   successiva" — AION usa semver, non interi, quindi "N+1" **non è un
   incremento numerico**: è il prossimo elemento dopo `AION_VERSION`
   nell'elenco ordinato delle release pubblicate.
4. **Versione target**: da `--version X.Y.Z` se passato (deve comparire
   nell'elenco ed essere > corrente, altrimenti errore), altrimenti
   l'ultima release dell'elenco. Se target == corrente, esce subito con
   "già aggiornato".
5. **Lock**: file di lock semplice (`data/.upgrade.lock`, stessa logica di
   `LockManager` in `upgrade_core.py` — pid+hostname+timestamp, stale dopo
   7200s) per evitare run concorrenti; reimplementato in bash o richiamando
   un piccolo helper Python condiviso.
6. **Backup**: un solo backup a inizio run (copre lo stato pre-upgrade,
   non uno per ogni hop intermedio), via `scripts/aion_backup.py` —
   scaricato al volo con `fetch()` se assente in un'installazione
   curl-only → `data/_backups/aion_backup_<ts>.tar.gz`.
7. **Loop sequenziale, un hop alla volta**: costruisce la catena di
   versioni da attraversare (es. corrente `1.4.0`, target `1.6.0`, elenco
   release → catena `[1.5.0, 1.6.0]`) e per ciascun `next` esegue, **in
   ordine, senza saltarne nessuno**:
   1. Re-fetch dei file top-level via `fetch()` (stesso pattern già in
      `install.sh`) dal ref `AION_REF=v<next>`: `docker-compose.ghcr.yml`,
      `docker/Caddyfile`, `scripts/apply_optimal_aion_env.py`,
      `scripts/env_tuning_profiles.py`.
   2. **Esegue il file di upgrade per `next`**, se presente (vedi sezione
      3 sotto) — è questo file che sa fare le modifiche specifiche a
      quella transizione (chiavi `.env` da aggiungere/rinominare, aggiustamenti
      di config). Se il file non esiste per quella versione, lo step è un
      no-op (la maggior parte delle release non introduce breaking change).
   3. Aggiorna **solo** la chiave `AION_VERSION=<next>` in `.env`
      esistente (sed/python in-place), preservando tutte le altre
      personalizzazioni. `config/` e `mcp_servers/` non vengono toccati
      (restano l'overlay scrivibile, sincronizzato dal container al boot
      via `AION_SYNC_ON_BOOT`, come già documentato).
   4. **Pull & restart**: `docker compose -f docker-compose.ghcr.yml pull
      && docker compose -f docker-compose.ghcr.yml up -d --no-build
      --remove-orphans`.
   5. **Health check**: riusa il polling già presente in `install.sh` su
      `/api/health` dopo il restart. Se fallisce, lo script si ferma qui
      (non prosegue con l'hop successivo): `AION_VERSION` in `.env`
      riflette l'ultimo hop riuscito, quindi un rerun di
      `install.sh upgrade` riprende dal punto giusto invece di ripetere
      hop già applicati (idempotenza/resumability "gratis").
   6. Log informativo: `docker compose exec -T backend alembic current`
      in sola lettura, solo per confermare che le migrazioni siano
      partite (pattern preso da `upgrade_core.py:1672-1679`) — le
      migrazioni vere restano automatiche al boot del backend
      (`src/data/migrations.py:run_migrations()`).
8. **Aggiorna `.aion-install.json`** con la nuova versione/timestamp (per
   coerenza, anche se resta write-only oggi) al termine dell'intera catena.
9. Rilascia il lock, stampa riepilogo (versione precedente → nuova,
   elenco hop attraversati, percorso backup, esito health check per hop).

**Vincolo di sequenzialità (hard requirement, non solo raccomandazione)**:
non è mai possibile passare direttamente da una versione a una non
immediatamente successiva nell'elenco release — lo script stesso
attraversa un hop alla volta e applica il file di upgrade di ciascuna
versione intermedia, mai un salto diretto al target.

### 3. Standard per i file di upgrade per-versione ("file X")

Ogni transizione N-1 → N che richiede un intervento specifico (nuove
chiavi `.env`, rinomina chiavi, aggiustamenti config) è codificata in un
file dedicato, scoperto ed eseguito dal loop dello step 2.7:

- **Percorso/naming**: `scripts/upgrades/<version>.py` (es.
  `scripts/upgrades/1.6.0.py`) — il nome è la versione **di arrivo**, non
  la coppia da/a: dato che le versioni sono totalmente ordinate
  nell'elenco release, "la versione di arrivo" identifica senza ambiguità
  anche quella di partenza (il suo predecessore nell'elenco). Stesso
  criterio già familiare da schemi di migrazione versionati (Alembic,
  Flyway). Directory nuova, committata nel repo insieme al resto del
  codice della release che la introduce.
- **Formato**: Python (non shell/YAML), per riusare direttamente gli
  helper di `upgrade_core.py` (`_ensure_*_env_keys()` e simili) invece di
  reimplementarli in bash. Contratto minimo: il file espone una funzione
  `def upgrade(ctx) -> None`, dove `ctx` porta i path della installazione
  corrente (`env_path`, `config_dir`, `install_dir`) e le utility di
  modifica idempotente dell'env già esistenti in `upgrade_core.py`
  (spostate/esposte in un piccolo modulo condiviso, es.
  `scripts/upgrade_lib.py`, importabile sia da `upgrade_core.py` sia dai
  file in `scripts/upgrades/`, così la logica non viene duplicata).
- **Esempio minimo** (`scripts/upgrades/1.6.0.py`):
  ```python
  def upgrade(ctx):
      ctx.ensure_env_key("AION_NEW_FEATURE_FLAG", "0")
      ctx.rename_env_key("AION_OLD_NAME", "AION_NEW_NAME")
  ```
- **Discovery in un'installazione curl-only**: dato che questi file
  vivono nel repo sorgente e l'installazione GHCR non ha una copia locale
  del repo, `install.sh upgrade` scarica (via `fetch()`, stesso
  meccanismo già usato per gli altri file) sia `scripts/upgrade_lib.py`
  sia, per ciascun hop, `scripts/upgrades/<next>.py` dal ref `v<next>`
  **prima** di eseguirlo — un 404 (file assente) viene trattato come
  no-op, non come errore.
- **Manutenzione futura**: quando una release introduce un breaking
  change che richiede un intervento a upgrade-time, aggiungere
  `scripts/upgrades/<nuova_versione>.py` diventa un item della checklist
  di rilascio (da documentare in `docs/opensource/releases.md` o
  `CONTRIBUTING.md`) — non è un passo automatico del pipeline CI, va
  scritto a mano insieme al codice che introduce il breaking change,
  nella stessa PR.

### 2. Version-check + notifica (nuovo, in scope)

- **Backend**: nuovo endpoint (es. `GET /admin/version-check` in
  `src/api/admin.py`, protetto da `require_admin_role` come gli altri
  endpoint `/admin/*`) che:
  - legge la versione corrente da `AION_VERSION` (env) o `version.json`,
  - interroga `https://api.github.com/repos/AION-by-ASA-Computer/AION_Agent/releases/latest`
    (con timeout breve e cache in-memory di qualche minuto per evitare
    rate-limit),
  - risponde `{ current, latest, update_available }`.
- **admin-ui**: componente banner non bloccante (stesso pattern del
  banner "cambia password" già presente in admin-ui — vedi
  `aion_admin_change_pw_skipped_until` in localStorage) che chiama
  l'endpoint al login/mount e mostra "Nuova versione X disponibile" con
  link alla changelog/release notes, mai un'azione di upgrade automatica.
- **chat-ui**: stessa informazione esposta in un punto secondario (es.
  badge nelle impostazioni admin, se già presente una sezione analoga),
  facoltativo/di minor priorità rispetto ad admin-ui.

## File critici da modificare/creare

- `scripts/install.sh` — modifica primaria: nuova modalità `upgrade`
  (parsing argomenti, funzioni backup/refetch/pull/health già in gran
  parte riusabili dal codice esistente dello script).
- `src/api/admin.py` (o nuovo modulo dedicato sotto `src/api/`) — nuovo
  endpoint version-check.
- `admin-ui/src/...` — nuovo componente notifica versione (riusa pattern
  banner esistente).
- `chat-ui/src/...` — eventuale badge secondario (opzionale).
- `docs/opensource/releases.md` — documentare il nuovo comando `install.sh
  upgrade` accanto al pattern `--version X.Y.Z` già documentato.
- `README.md` — aggiungere one-liner di upgrade accanto a quello di
  install già presente (riga 87).

## Verifica end-to-end

1. Installazione pulita in una dir di test con `install.sh` (versione
   pinned N).
2. Bump manuale di `AION_VERSION` "a monte" (o uso di `--version N+1`) e
   run di `install.sh upgrade`: verificare che
   - venga creato un backup in `data/_backups/`,
   - `.env` abbia `AION_VERSION` aggiornato e tutte le altre chiavi
     invariate,
   - `docker compose ps` mostri i 4 servizi GHCR sul nuovo tag immagine,
   - `/api/health` risponda 200 dopo il restart,
   - `config/` e `mcp_servers/` locali non siano stati sovrascritti/persi.
3. Run di `install.sh upgrade` una seconda volta senza cambi di versione:
   deve uscire subito con "già aggiornato", nessun downtime.
4. Verifica lock: due run concorrenti di `install.sh upgrade` — la
   seconda deve fallire/attendere segnalando il lock attivo.
5. `curl -H "Authorization: Bearer <admin-token>" /admin/version-check`
   ritorna `current`/`latest`/`update_available` corretti (testare sia con
   versione allineata che disallineata).
6. Login in admin-ui con una versione desallineata: verificare comparsa
   del banner di notifica, dismissibile, non bloccante.
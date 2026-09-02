# Handoff — Upgrade Docker/GHCR e persistenza dati

**Branch:** `claude/docker-upgrade-persistence-76jo2j`
**Commit:** `b30fc50` — *fix(docker): make GHCR overlay actually run the pulled image*
**Data:** 2026-09-02
**Stato:** primo step implementato e pushato. Restano 4 step (vedi §6).

> Questo file riassume una sessione di analisi. Serve a riprendere il lavoro da
> una sessione locale senza rileggere tutta la chat. Cancellabile una volta
> chiuso il lavoro.

---

## 1. Domanda di partenza

Quando un cliente aggiorna le immagini pubblicate su GHCR:

1. non viene lanciato `upgrade-aion.sh`, quindi manca la riconciliazione di `.env`/config;
2. come si garantisce che skill, profili e memoria **non** vengano persi?

---

## 2. Com'è fatto oggi il sistema (stato accertato leggendo il codice)

### 2.1 `upgrade-aion.sh`

È un wrapper bash sottile: banner ASCII, trova un Python, decide se aggiungere
`--prepare-runtime` (solo se **non** `--dry-run` e **non** `--docker`), poi
`exec` su `scripts/upgrade_core.py` (1974 righe), che è l'orchestratore vero.

**Non fa `git pull` e non scarica immagini dell'app.** Presuppone che il codice
nuovo ci sia già. Il suo compito è riconciliare tutto ciò che sta **fuori**
dall'immagine: `.env`, `config/`, `mcp_servers/`, schema DB, `.venv`.

### 2.2 Path bare-metal (`main()`, righe ~1670-1974)

1. Lock `data/.upgrade.lock` (PID + hostname + ts, stale > 2h)
2. `_ensure_runtime()` — crea/allinea `.venv` con uv (fallback pip)
3. Preflight: verifica esistenza di 6 script obbligatori
4. **Backup bloccante** — `scripts/aion_backup.py` → `data/_backups/*.tar.gz`
5. `_migrate_env_legacy_keys` (`AION_CHAINLIT_*` → `AION_CHAT_*`) + `_migrate_docker_data_paths_in_env`
6. ~17 × `_ensure_*_env_keys()` — aggiungono al `.env` le chiavi nuove della release
7. `ensure_skill_packages.py` → `sync_config` (safe) + `--skills-only --force` + `sync_proprietary_config --force` + `sync_mcp_servers --force`
8. `_patch_sql_query_memory_config`, `_patch_mempalace_navigation_config`
9. `runtime_extras_setup.py` (fs policy, Playwright)
10. `setup_core.py` — rigenera/normalizza il `.env` finale
11. `_prune_junk_profile_files()` — elimina `*_OLD.yaml`, `* copy.yaml`
12. `init_unified_db.py` — bootstrap schema + FTS5 + trigger + **Alembic** + backfill timeline
13. `_warmup_chroma_embeddings`, `seed_mcp_integration_configs.py`
14. `--with-legacy` (opz.): `migrate_to_aion_db.py`, `migrate_fs_to_storage.py`; `--with-destructive` richiede di digitare `UNIFY`
15. Verifiche: `import src.api.main`, `alembic current`, `check_env_example_coverage.py`

### 2.3 Path `--docker` (`_docker_upgrade()`, righe 1402-1624)

Stessi passi 4-9 (backup, migrazioni env, tutte le `_ensure_*`, skill/MCP sync,
patch, extras, warmup, env coverage) **eseguiti sull'host**, poi:

- `docker compose pull --ignore-buildable --policy missing` → solo immagini base (caddy, redis)
- `docker compose build --pull` → **ricostruisce le 4 immagini app dal repo locale**
- `docker compose up -d --remove-orphans`
- `sleep 3` + `docker compose exec -T backend alembic current` (solo check read-only:
  le migration le applica il backend al boot via `src.data.migrations.run_migrations()`)
- `docker image prune -f`

**Il path `--docker` è quindi build-from-source, non GHCR.**

#### Drift accertato tra i due path

Presenti in bare-metal, assenti in `--docker`:

| Passo | Giudizio |
|---|---|
| `_ensure_runtime()` (venv) | legittimo — deps nell'immagine |
| `init_unified_db.py` | legittimo — Alembic gira al boot del container |
| `import src.api.main` | legittimo — sostituito dall'healthcheck compose |
| migrazioni legacy (`--with-legacy`) | mai cablate nel path Docker |
| `setup_core.py` | **buco** — manca la normalizzazione finale del `.env` |
| `_ensure_skill_view_env_keys` | **buco** — probabile svista (c'è `skill_lifecycle` accanto) |
| `_prune_junk_profile_files` | **buco** — i profili `*_OLD` restano e vengono caricati |
| `seed_mcp_integration_configs.py` | **buco** — nuove integrazioni MCP non seminate |

Causa: `_docker_upgrade()` è una funzione separata che duplica ~20 chiamate.
Ogni nuova `_ensure_*` va aggiunta in due punti e prima o poi si dimentica.

### 2.4 Cosa contiene l'immagine `aion-backend`

Definito in **tre file in cascata**:

1. **`docker/Dockerfile.backend`** — le `COPY` dello stage runtime:
   - riga 69: tesseract(+ita), poppler, libmagic1, tini, curl, git, nodejs, npm, **podman**, libreoffice
   - riga 85: `/opt/venv` con tutte le deps di `requirements.txt` (buildate con uv)
   - riga 88: binari `uv`/`uvx`
   - righe 94-100: `src/`, `mcp_servers_std/`, `config_std/`, `migrations/`, `scripts/`, `wren/`, `alembic.ini`
   - righe 104-105: `RUN sync_config.py --force` + `sync_mcp_servers.py --force` → genera `/app/config` e `/app/mcp_servers` **nell'immagine**
   - riga 109: dir vuote `/app/data/{sessions,profiles,skills/generated,agent_dbs}`
2. **`.dockerignore`** — filtra il build context *prima* delle COPY (esclude `.git`, `.venv`, `node_modules`, `data/`, `*.db`, `.env*`, …). Contenuto reale = `.dockerignore ∩ COPY`.
3. **`.github/workflows/release-images.yml`** — matrice immagine→Dockerfile→build-args,
   `context: .`, `ref: <tag della release>`, `platforms: linux/amd64,linux/arm64`,
   tag `X.Y.Z` + `latest`, label `org.opencontainers.image.version`.

Frontend (`chat-ui`, `admin-ui`): bundle Next.js standalone già compilato, con
`NEXT_PUBLIC_AION_API_URL=/api` **compilato dentro il JS** (build-arg → non
cambiabile a runtime). `website`: solo output statico Docusaurus su nginx.
Le tre immagini frontend non hanno bind-mount: sono autosufficienti.

### 2.5 Il problema centrale (era il vero bug)

`docker-compose.yml` montava sopra l'immagine del backend:

```yaml
- ./src:/app/src:ro
- ./config_std:/app/config_std:ro
- ./mcp_servers_std:/app/mcp_servers_std:ro
```

Un bind-mount **copre sempre** il contenuto dell'immagine a quel path.
`docker-compose.ghcr.yml` sostituiva solo `image:`, lasciando i mount.

Risultato: in modalità GHCR l'immagine forniva solo venv + pacchetti di sistema +
`migrations/` + `scripts/`, mentre **il codice applicativo continuava ad arrivare dal
clone git**. Quindi:

- `docker compose pull` senza `git pull` → deps nuove + **migration nuove** che
  girano contro **codice vecchio**;
- `git pull` senza pull dell'immagine → codice nuovo su deps vecchie.

Era una scelta deliberata per il deploy build-from-source (il commento nel compose
dice *"git pull + restart propagates without image rebuild"*), che però rende
inutilizzabile il flusso GHCR.

### 2.6 Cosa invece funziona già bene

- **Volume `aion_data`**: sopravvive a pull/rebuild/up. Skill generate, profili, SQLite, sessioni sono lì.
- **Overlay `config/` + `mcp_servers/`**: scrivibili, sincronizzati da `*_std` al boot
  da `docker/backend-entrypoint.sh` (`AION_SYNC_ON_BOOT`, default 1).
- **`src/runtime/profile_sync_state.py`**: hash-diffing per profilo. Un profilo YAML
  modificato dall'utente viene **preservato** anche con `--force`; solo quelli identici
  al template vengono aggiornati. Stato in `config/profiles/.aion-sync-state.json`.
- **`sync_config.py::_NEVER_FORCE_OVERWRITE`**: `mcp_registry.yaml` / `.local.yaml` mai sovrascritti.
- **Alembic al boot** del backend: gira comunque, qualunque sia il metodo di aggiornamento.

---

## 3. Migrazioni di dati: come gestire un cambio importante (es. nuovo sistema di memoria)

### Tre classi di stato, tre meccanismi

| Classe | Dove vive | Meccanismo |
|---|---|---|
| A — dati relazionali | `data/aion.db` (`ltm_notes`, `ltm_entities`, `messages`…) | **Alembic**: schema + backfill nella *stessa* revision |
| B — stato fuori dal DB | Chroma (embeddings), drawer MemPalace, file in `data/` | **Job idempotente con registro di stato** |
| C — config/template | `config/profiles/`, `config/skills/`, `mcp_registry.yaml` | `sync_config.py` con hash-preserve (già c'è) |

### Classe A — già corretta

`migrations/versions/o7p8q9r017_mnemos_projects_ltm.py` è il modello giusto:
non solo `create_table`, ma `_consolidate_projects_table()` che sposta i dati,
controlla i conteggi righe e **fallisce esplicitamente** (`raise RuntimeError`) su casi
ambigui. Introspezione (`_table_names`, `_columns`) prima di ogni DDL → idempotente.
E gira da sola al boot del container.

### Classe B — buco accertato

Alembic non può: è sincrono, gira prima che MCP/Chroma siano su, e un backfill con
chiamate LLM su 50k messaggi bloccherebbe l'avvio.

Esiste già `scripts/migrate_alibr_project_memory.py` (sposta drawer MemPalace +
riassegna `cached_sql_queries`, ha `--dry-run`) ma è **one-shot manuale**: nessuno lo
lancia, nulla registra se è già stato eseguito.

**Manca un registro delle data-migration applicate.** Verificato: nessuna tabella
`data_migrations` / `schema_version` / `app_version` in `src/data/`.

Serve:

```
data_migrations(id TEXT PK, applied_at, status, rows_processed, error)
```

più un runner post-boot (servizi già su) che esegue i job non ancora `done`, in
background, resumable via checkpoint su `rows_processed`, con stato esposto in
`/health` o nell'admin UI. Ogni job: `id` stabile (es. `2026_10_ltm_v2_backfill`),
`--dry-run`, idempotente per riga.

### La regola che protegge davvero i dati: expand → migrate → contract

Mai cutover in una sola release. Tre release:

- **v1.4 (expand)** — crea le strutture nuove, l'agent **scrive su entrambi** i sistemi, legge dal vecchio. Rollback a v1.3 sicuro.
- **v1.5 (migrate)** — il backfill popola il nuovo store con lo storico; l'agent legge dal nuovo **con fallback al vecchio**. Dual-write continua.
- **v1.6 (contract)** — solo dopo che il backfill risulta `done` su quel deployment, si smette di scrivere sul vecchio e lo si dismette (rinominare, non cancellare).

**Corollario duro:** la release che introduce la memoria nuova non deve mai cancellare
quella vecchia. Su SQLite il `downgrade` Alembic spesso non è praticabile (niente
`ALTER COLUMN`): il vero rollback è il **restore del backup**.

---

## 4. Modifiche già fatte (commit `b30fc50`)

### `docker-compose.ghcr.yml` — riscritto

Il file ora fa **due** cose, non una: sostituisce `image:` **e** riscrive la lista
`volumes` del backend con il tag YAML `!override`, tenendo solo lo stato:

```yaml
backend:
  image: ghcr.io/aion-by-asa-computer/aion-backend:${AION_VERSION:-latest}
  volumes: !override
    - aion_data:/app/data
    - ./.env:/app/.env:ro
    - ./data/sessions:/app/data/sessions
    - ./data/db_test:/app/data/db_test
    - ~/.wren:/app/data/wren/.wren:ro
    - ${AION_PODMAN_SOCKET_HOST:-/run/user/1000/podman/podman.sock}:/run/podman/podman.sock
    - ./config:/app/config
    - ./mcp_servers:/app/mcp_servers
```

Rimossi: `./src`, `./config_std`, `./mcp_servers_std`, `./requirements-sandbox-skills.txt`.
Tutto il resto (environment, healthcheck, networks, depends_on, extra_hosts, ulimits,
Caddy, Redis, volumi nominati) resta ereditato dal file base.

### `docker/Dockerfile.backend`

Aggiunti due `COPY` per file che finora arrivavano **solo** via bind-mount e che
sarebbero spariti togliendo i mount:

```dockerfile
COPY version.json      ./
COPY requirements-sandbox-skills.txt ./
```

`version.json` serve a `_read_version()` in `upgrade_core.py` / `sync_config.py`
(altrimenti dentro il container la versione risulta `"unknown"`) e servirà al version gating.

### `docs/opensource/releases.md`

Documentati: perché servono due modifiche e non una, l'obbligo di `--no-build`,
il requisito **Compose ≥ 2.24** (tag `!override`), e che in modalità GHCR il
`git pull` esce dal flusso di upgrade.

### Verifica eseguita

`docker compose -f docker-compose.yml -f docker-compose.ghcr.yml config` (Compose v5.1.1):

```
image: ghcr.io/aion-by-asa-computer/aion-backend:1.4.0
volumes backend: aion_data, .env, data/sessions, data/db_test, ~/.wren,
                 podman.sock, config, mcp_servers      ← src/ non c'è più
chat-ui / admin-ui / website → :1.4.0
build presente: True                                   ← per questo serve --no-build
```

**Non** testato: pull reale delle immagini da GHCR e deploy end-to-end (l'ambiente
remoto non aveva accesso a GHCR). La verifica è sul merge della configurazione.

### Decisione presa

Avevo proposto `${AION_VERSION:?}` per rendere obbligatorio il pin di versione.
Ho lasciato `${AION_VERSION:-latest}` perché il `:?` avrebbe rotto il comando già
documentato per dev/staging (`docker compose ... pull` senza esportare la variabile).
Il pin resta raccomandato nei commenti e nella doc. Se lo vuoi bloccante, è una riga.

---

## 5. Nota su `--no-build`

La sezione `build:` del file base **non è rimovibile** da un override. Quindi tutti i
comandi in modalità GHCR devono passare `--no-build`, altrimenti Compose ricostruisce
l'immagine dal sorgente locale quando non la trova in cache.

```bash
AION_VERSION=1.4.0 docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull
AION_VERSION=1.4.0 docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d --no-build
```

---

## 6. Lavoro rimanente (in ordine)

### Step 2 — `--reconcile-only` + refactor di `upgrade_core.py`

Le `_ensure_*_env_keys` della versione N+1 le conosce **solo il codice della versione
N+1**. Se lo script gira sull'host da un clone fermo alla N, aggiunge le chiavi vecchie.
Siccome `scripts/` è già dentro l'immagine, va eseguito in un container effimero della
**nuova** immagine:

```bash
docker compose -f docker-compose.yml -f docker-compose.ghcr.yml \
  run --rm --no-deps \
  -v "$PWD/.env:/app/.env:rw" \
  -v "$PWD/data/_backups:/app/data/_backups:rw" \
  --entrypoint python \
  backend scripts/upgrade_core.py --reconcile-only
```

(nota il `.env` montato **rw** invece di `ro`, solo per questo container)

Refactor in tre blocchi, per chiudere il drift di §2.3:

```
reconcile_state()   ← .env + config + skill/MCP sync + prune. Host (bare-metal) o container (GHCR)
prepare_runtime()   ← venv/uv.               Solo bare-metal
orchestrate_*()     ← compose build|pull + up. Solo Docker
```

Entry point sottili: `--prepare-runtime` → prepare + reconcile + db;
`--docker` → reconcile(host) + build + up; `--ghcr` → pull + reconcile(container) + up.
Una chiave nuova si aggiunge in **un posto solo**.

### Step 3 — ramo `--ghcr` nello script di upgrade

Ordine obbligato (la riconciliazione va **dopo** il pull e **prima** dell'up):

1. **Preflight** — lock, `.env` presente, spazio disco, `AION_VERSION` valorizzata,
   versione target ≥ corrente (leggila con `docker inspect` dalla label
   `org.opencontainers.image.version`)
2. **Backup** — `docker compose run --rm --entrypoint python backend scripts/aion_backup.py --output /app/data/_backups`
   (gira col Python dell'immagine, scrive sull'host). Se fallisce → stop
3. **Pull** — `docker compose ... pull`
4. **Reconcile** — il `run --rm` dello Step 2, con l'immagine **nuova**
5. **Up** — `up -d --no-build --remove-orphans` (l'entrypoint fa sync + Alembic)
6. **Verify** — attendi `healthy` (`docker compose ps --format json`, timeout ~180s
   dato lo `start_period: 90s`), poi `exec backend alembic current` + `curl /health`
7. **Rollback su fallimento** — `AION_VERSION=<precedente> up -d` + istruzioni restore.
   Salva il tag precedente in un file di stato **prima** del pull
8. **Prune** — `docker image prune -f`

### Step 4 — estendere `aion_backup.py`

Oggi archivia solo: `data/aion.db`, `data/chat_memory.db`, `config/default.yaml`,
`config/mcp_registry.yaml`, `config/mcp_registry.local.yaml`, `data/plugins`,
`data/deep_research`.

**Mancano** `config/profiles/`, `config/skills/` e il vector store Chroma — cioè
esattamente le personalizzazioni del cliente. Senza, il backup non riporta indietro.

### Step 5 — version gating

Tabella `aion_meta(app_version)` scritta al boot: se l'immagine è **più vecchia** dello
schema registrato, il backend rifiuta di partire con messaggio chiaro. Senza questo, un
rollback maldestro fa girare codice vecchio su schema nuovo e i dati si corrompono.

### Step 6 (opzionale) — chiudere i buchi del path `--docker`

`setup_core.py`, `_ensure_skill_view_env_keys`, `_prune_junk_profile_files`,
`seed_mcp_integration_configs.py`. Il refactor dello Step 2 li chiude da solo.

---

## 7. Decisione aperta

Nel modello "puro immagine" il clone git sul server del cliente serve solo per `.env`,
i compose file e `scripts/upgrade-aion.sh`.

**Va bene, o esistono clienti a cui serve poter patchare `src/` a caldo sul server?**
(è probabilmente il motivo per cui il mount `./src` esisteva). Se sì, il disegno cambia:
serve un mount opzionale attivabile su richiesta — es. un terzo file
`docker-compose.hotpatch.yml` — non attivo di default.

---

## 8. Comandi utili

```bash
# recuperare il branch
git fetch origin claude/docker-upgrade-persistence-76jo2j
git checkout claude/docker-upgrade-persistence-76jo2j
git diff main...HEAD

# verificare il merge dei compose
AION_VERSION=1.4.0 docker compose -f docker-compose.yml -f docker-compose.ghcr.yml config

# ispezionare un'immagine pubblicata
docker run --rm --entrypoint ls ghcr.io/aion-by-asa-computer/aion-backend:latest -la /app
docker history ghcr.io/aion-by-asa-computer/aion-backend:latest
docker image inspect ghcr.io/aion-by-asa-computer/aion-backend:latest --format '{{json .Config.Labels}}'

# dimostrare il problema dei mount (prima del fix)
docker run --rm --entrypoint ls ghcr.io/aion-by-asa-computer/aion-backend:latest /app/src  # codice della release
docker compose exec backend ls /app/src                                                    # codice del clone git
```

---
title: Passaggio da docker-compose.yml a docker-compose.ghcr.yml
sidebar_position: 6
description: Guida passo-passo per fare il backup completo e passare dallo stack compilato in locale (docker-compose.yml) alle immagini GHCR (docker-compose.ghcr.yml) senza perdere dati.
---

# Passaggio da `docker-compose.yml` a `docker-compose.ghcr.yml`

Questa guida porta un'installazione avviata finora con `docker-compose.yml`
(immagini `aion/*` compilate dal clone) a `docker-compose.ghcr.yml` (immagini
`ghcr.io/aion-by-asa-computer/aion-*`), **nella stessa cartella** e **senza
perdere dati**.

## Perché i dati non si perdono

- Entrambi i file hanno `name: aion-agent`: i volumi si chiamano sempre
  `aion-agent_aion_data`, `aion-agent_redis_data`, `aion-agent_caddy_data`,
  `aion-agent_caddy_config`. Il nuovo stack si aggancia ai volumi esistenti.
- Il DB (`/app/data/aion.db`: chat, utenti, impostazioni, credenziali cifrate)
  vive nel volume `aion_data`, con lo stesso `AION_DB_URL` in entrambi i file.
- I bind mount `./.env`, `./config`, `./mcp_servers`, `./data/sessions`,
  `./data/db_test` sono identici.

Cambiano solo le immagini (il codice). Le differenze da gestire sono elencate
nei passi sotto: overlay MCP, versione/migrazioni Alembic, file di override.

:::danger Regole d'oro
- **Mai** `docker compose down -v` sullo stack reale: `-v` cancella i volumi.
- Non toccare `AION_CREDENTIAL_ENCRYPTION_KEY`, `REDIS_PASSWORD`,
  `AION_CHAT_AUTH_SECRET` nel `.env`.
- Esegui **tutti** i comandi nello **stesso terminale** (le variabili
  `export` valgono solo lì) e dalla **root del clone**.
:::

---

## 0. Variabili di lavoro

```bash
cd /percorso/del/clone/AION_Agent
```

### Scegli la versione delle immagini

**Opzione A: ultima release pubblicata (niente build locale).** Le immagini
vengono scaricate da GHCR. È la scelta per la produzione e l'unica con cui
funzionano gli aggiornamenti automatici (`install.sh upgrade`, pulsante
"Aggiorna ora").

Con la CLI `gh`:

```bash
export AION_TARGET=$(gh release view --repo AION-by-ASA-Computer/AION_Agent --json tagName -q .tagName | sed 's/^v//') && echo "Release: $AION_TARGET"
```

Senza `gh` (stessa chiamata usata da `install.sh`):

```bash
export AION_TARGET=$(curl -fsSL https://api.github.com/repos/AION-by-ASA-Computer/AION_Agent/releases/latest | python3 -c "import sys, json; print(json.load(sys.stdin)['tag_name'].lstrip('v'))") && echo "Release: $AION_TARGET"
```

Per una release specifica: `export AION_TARGET=1.6.2` (senza la `v`).

**Opzione B: immagini compilate in locale** con i nomi GHCR
(`bash ./scripts/install.sh --local` o `build_local_images`), tag `local`.
Serve quando il codice del clone è più nuovo dell'ultima release.

```bash
export AION_TARGET=local
```

:::caution Release e DB già migrato
Se il DB è già stato migrato da un codice più nuovo dell'ultima release (ad
esempio da un avvio con immagini `local` o con il compose di default su un
branch non rilasciato), l'opzione A non è utilizzabile finché non esce una
release che contiene quelle migrazioni. Il check del passo **1c** lo rileva.
In quel caso usa l'opzione B ora e passa alla release più avanti (passo 9).
:::

Cartella di backup (fuori dal clone, con timestamp):

```bash
export BK=~/aion-backups/pre-ghcr-$(date +%Y%m%d_%H%M%S) && mkdir -p "$BK" && echo "$BK"
```

Funzione di comodo per il nuovo stack: include `docker-compose.override.yml`
se presente (con `-f` non viene più caricato in automatico).

```bash
dcg() { if [ -f docker-compose.override.yml ]; then docker compose -f docker-compose.ghcr.yml -f docker-compose.override.yml "$@"; else docker compose -f docker-compose.ghcr.yml "$@"; fi; }
```

---

## 1. Controlli preliminari (stack vecchio ancora acceso)

**1a. Modifiche locali al codice.** Con GHCR `src/`, `config_std/` e
`mcp_servers_std/` non sono più montati: valgono quelli dell'immagine.
Modifiche non committate/non rilasciate smettono di avere effetto.

```bash
git status --short src config_std mcp_servers_std
```

**1b. Immagini disponibili.** Per una release va prima fatto il pull (lo
stack vecchio resta acceso, così il fermo è più breve); per `local` devono già
esistere.

```bash
[ "$AION_TARGET" != "local" ] && AION_VERSION=$AION_TARGET docker compose -f docker-compose.ghcr.yml pull
```

Se il pull risponde `denied` o `unauthorized`, le immagini richiedono il login
a GHCR (token GitHub con scope `read:packages`):

```bash
docker login ghcr.io
```

```bash
for s in backend chat-ui admin-ui website; do docker image inspect ghcr.io/aion-by-asa-computer/aion-$s:$AION_TARGET >/dev/null 2>&1 && echo "ok     aion-$s:$AION_TARGET" || echo "MANCA  aion-$s:$AION_TARGET"; done
```

Se una riga dice `MANCA`, fermati.

**1c. Compatibilità del DB (Alembic).** La revision attuale del DB deve
essere nota alla nuova immagine, altrimenti il backend non parte. La revision
si legge direttamente dalla tabella `alembic_version`: `alembic current`
fallirebbe se il DB fosse già più avanti del codice vecchio.

```bash
REV=$(docker compose exec -T backend python -c "import sqlite3; print(sqlite3.connect('file:data/aion.db?mode=ro', uri=True).execute('select version_num from alembic_version').fetchone()[0])" 2>/dev/null); echo "Revision DB: $REV"
```

```bash
if [ -n "$REV" ] && docker run --rm --entrypoint alembic ghcr.io/aion-by-asa-computer/aion-backend:$AION_TARGET history 2>/dev/null | grep -q "$REV"; then echo "OK: la nuova immagine conosce $REV"; else echo "STOP: la nuova immagine NON conosce '$REV' (troppo vecchia o errore)"; fi
```

Con `STOP` non proseguire: serve una versione più recente (con l'opzione A,
passa all'opzione B e vedi il passo 9). Non fidarti del solo healthcheck: se
le migrazioni falliscono, il backend logga
`ERROR … Errore durante le migrazioni Alembic` ma parte comunque `healthy`,
con un codice che non conosce lo schema del DB.

:::caution DB già più avanti dello stack vecchio
Se nei log dello stack vecchio compare
`Can't locate revision identified by '<rev>'`, il DB è già stato migrato da
un'immagine più nuova (ad esempio un avvio precedente del compose GHCR) e il
codice vecchio gira su uno schema che non conosce. Non è una perdita di dati:
il passaggio a un'immagine che conosce quella revision (check `OK` sopra)
riallinea codice e DB.

```bash
docker compose logs backend | grep -iE "alembic|migrat" | tail -5
```
:::

**1d. Cartella `~/.wren`.** Il compose GHCR la monta; se manca Docker la crea
(su Linux con owner root).

```bash
mkdir -p ~/.wren
```

---

## 2. Backup

**2a. Backup logico** (stack acceso), poi copiato nella cartella di backup:

```bash
docker compose exec backend python scripts/aion_backup.py --output /app/data/_backups
```

```bash
mkdir -p "$BK/backup-logico" && docker compose cp backend:/app/data/_backups/. "$BK/backup-logico/"
```

**2b. Ferma lo stack vecchio.** Senza `-v`.

```bash
docker compose down
```

**2c. Backup dei volumi** (a stack fermo, così la copia di SQLite è
consistente):

```bash
for v in aion_data redis_data caddy_data caddy_config; do docker run --rm -v aion-agent_$v:/v:ro -v "$BK:/b" alpine tar -czpf /b/$v.tar.gz -C /v . && echo "ok $v"; done
```

**2d. Backup dei file sull'host** (`.env` incluso, contiene i segreti: tieni
la cartella al sicuro):

```bash
tar -czpf "$BK/host-files.tar.gz" .env config mcp_servers data/sessions data/db_test $( [ -f docker-compose.override.yml ] && echo docker-compose.override.yml ) && echo ok
```

```bash
git rev-parse HEAD > "$BK/git-commit.txt" && docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep '^aion/' > "$BK/old-images.txt"
```

**2e. Verifica il backup.**

```bash
ls -lh "$BK" && tar -tzf "$BK/aion_data.tar.gz" | grep -E '^\./aion\.db$' && echo "DB presente nel backup"
```

---

## 3. Fotografia dei dati "prima"

Script che conta le righe di ogni tabella del DB (l'URI SQLite è passato come
argomento):

```bash
cat > "$BK/count.py" <<'EOF'
# Conta le righe di ogni tabella del DB AION: serve a confrontare prima/dopo il passaggio.
import sqlite3, sys
c = sqlite3.connect(sys.argv[1], uri=True)
for (t,) in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by 1"):
    try:
        print(t, c.execute(f'select count(*) from "{t}"').fetchone()[0])
    except Exception as e:
        print(t, "ERR", e)
EOF
```

Conteggio sul volume (stack fermo), con l'immagine vecchia:

```bash
docker run --rm -i --entrypoint python -v aion-agent_aion_data:/d:ro aion/backend:latest - "file:/d/aion.db?immutable=1" < "$BK/count.py" > "$BK/before.txt" && wc -l "$BK/before.txt"
```

---

## 4. Aggiorna il `.env`

Imposta le chiavi senza aprire il file: le righe esistenti con la stessa
chiave vengono rimosse e riscritte in fondo; le righe commentate restano.

- `AION_VERSION`: tag delle immagini GHCR (deve essere esplicito, non `latest`).
- `AION_MCP_REGISTRY_LOCAL_PATH`: mantiene l'overlay MCP dove stava
  (`./config/mcp_registry.local.yaml`). Il default del compose GHCR punterebbe
  a `/app/data/…` e i server MCP aggiunti dall'admin sembrerebbero spariti.

```bash
[ -n "$(tail -c1 .env)" ] && echo >> .env; for kv in "AION_VERSION=$AION_TARGET" "AION_MCP_REGISTRY_LOCAL_PATH=/app/config/mcp_registry.local.yaml"; do k=${kv%%=*}; sed -i '' "/^${k}=/d" .env; echo "$kv" >> .env; done
```

```bash
grep -E '^(AION_VERSION|AION_MCP_REGISTRY_LOCAL_PATH)=' .env
```

:::note Linux
`sed -i ''` è la sintassi macOS; su Linux usa `sed -i`.
:::

**Immagine sandbox (opzionale, consigliata con l'opzione A).** La sandbox
resta `aion/sandbox:latest`, compilata dal clone, finché non punti
all'immagine GHCR. Non tocca i dati: puoi farlo anche dopo. L'immagine deve
essere presente in **Podman**, non in Docker.

Opzione A (release):

```bash
podman pull ghcr.io/aion-by-asa-computer/aion-sandbox:$AION_TARGET
```

Opzione B (`local`, copia da Docker a Podman):

```bash
docker save ghcr.io/aion-by-asa-computer/aion-sandbox:local | podman load
```

Poi in `.env`:

```bash
k=AION_SANDBOX_CONTAINER_IMAGE; sed -i '' "/^${k}=/d" .env; echo "$k=ghcr.io/aion-by-asa-computer/aion-sandbox:$AION_TARGET" >> .env
```

---

## 5. Avvio con `docker-compose.ghcr.yml`

```bash
dcg up -d
```

Attendi che `backend` sia `healthy` (fino a ~2 minuti al primo avvio, le
migrazioni girano al boot):

```bash
dcg ps
```

```bash
dcg logs backend | grep -iE 'alembic|migrat|aion-entrypoint|error|traceback'
```

---

## 6. Verifica

**6a. Revision DB** allineata alla nuova immagine:

```bash
dcg exec backend alembic current
```

**6b. Confronto dei dati** (lettura in sola lettura sul DB in uso):

```bash
dcg exec -T backend python - "file:/app/data/aion.db?mode=ro" < "$BK/count.py" > "$BK/after.txt" && diff "$BK/before.txt" "$BK/after.txt" && echo "Nessuna differenza"
```

Esito atteso: nessuna tabella esistente con **meno** righe. Sono normali
tabelle nuove (migrazioni) e variazioni sulle tabelle interne FTS
(`*_data`, `*_idx`, `*_docsize`, `*_config`).

**6c. Controlli da UI** (`http://localhost` o `https://<DOMAIN>`):

- [ ] login con un utente esistente
- [ ] storico chat nella sidebar, apertura di una conversazione vecchia
- [ ] profili e progetti
- [ ] admin-ui → server MCP personalizzati presenti
- [ ] admin-ui → provider LLM: invio di un messaggio funziona (conferma che
      la chiave di cifratura è corretta)
- [ ] canali (Telegram/WhatsApp) se configurati

---

## 7. Dopo il passaggio

**Usa sempre il compose GHCR.** Un `docker compose up -d --build` col file di
default riporterebbe lo stack sulle immagini `aion/*`. Per renderlo il
default della cartella, aggiungi `COMPOSE_FILE` al `.env` (con l'override solo
se il file esiste):

```bash
echo "COMPOSE_FILE=docker-compose.ghcr.yml$( [ -f docker-compose.override.yml ] && echo :docker-compose.override.yml )" >> .env
```

Da quel momento `docker compose ps/logs/exec/up` usano GHCR. Nota:
`scripts/install.sh` usa sempre e solo `-f docker-compose.ghcr.yml`, quindi
negli upgrade automatici l'override non viene applicato.

**Aggiornamenti successivi (solo opzione A).** Con `AION_VERSION=X.Y.Z` le
release nuove si installano con lo script, che fa backup, pull e migrazioni
hop per hop:

```bash
bash scripts/install.sh upgrade
```

Con `AION_VERSION=local` l'upgrade non è supportato, salvo modalità ibrida:
vedi [self-update](./self-update.md) e il passo 9.

**Pulsante "Aggiorna ora" nell'admin-ui (opzionale, solo opzione A).** Serve
il sidecar `updater`, che si attiva con `COMPOSE_PROFILES=updater` e le chiavi
`AION_HOST_*`. `install.sh upgrade` le scrive da solo, ma solo se c'è
davvero un aggiornamento: se sei già all'ultima release esce prima. In quel
caso aggiungile così (solo quelle mancanti; `AION_HOST_DOCKER_GID=0` vale per
Docker Desktop su macOS, su Linux usa `stat -L -c %g /var/run/docker.sock`):

```bash
add() { grep -q "^$1=" .env || echo "$1=$2" >> .env; }; add AION_HOST_INSTALL_DIR "$PWD"; add AION_HOST_HOME "$HOME"; add AION_HOST_UID "$(id -u)"; add AION_HOST_GID "$(id -g)"; add AION_HOST_DOCKER_GID 0; add AION_UPDATER_TOKEN "$(openssl rand -hex 32)"; add COMPOSE_PROFILES updater
```

```bash
dcg up -d updater && dcg ps updater
```

**Pulizia (solo dopo qualche settimana senza problemi):**

```bash
docker volume rm aion-agent_uv_cache
```

```bash
docker image rm aion/backend:latest aion/chat-ui:latest aion/admin-ui:latest aion/website:latest
```

---

## 8. Rollback

Le migrazioni applicate dalla nuova immagine possono rendere il DB
incompatibile con il codice vecchio: il rollback **ripristina sempre i volumi
dal backup**. Le chat create dopo il passaggio vanno perse.

Nello stesso terminale (servono `$BK` e `dcg`; se il terminale è nuovo,
reimposta `BK` col percorso della cartella di backup e ridefinisci `dcg`):

```bash
dcg down
```

```bash
for v in aion_data redis_data caddy_data caddy_config; do docker run --rm -v aion-agent_$v:/v -v "$BK:/b:ro" alpine sh -c "find /v -mindepth 1 -delete && tar -xzpf /b/$v.tar.gz -C /v" && echo "ripristinato $v"; done
```

```bash
tar -xzpf "$BK/host-files.tar.gz" && echo "file host ripristinati"
```

```bash
docker compose -f docker-compose.yml up -d
```

Il ripristino di `host-files.tar.gz` riporta anche il `.env` originale (senza
`AION_VERSION`, `COMPOSE_FILE`, ecc.). Le immagini `aion/*` sono ancora in
locale (elenco in `$BK/old-images.txt`), quindi non serve ricompilare.

---

## 9. Da `local` all'ultima release (in seguito)

Se hai fatto il passaggio con l'opzione B perché il DB era più avanti
dell'ultima release, passa alla release appena ne esce una che contiene le
stesse migrazioni. I dati restano nei volumi: cambia solo il tag.

Definisci di nuovo le variabili del passo 0 (opzione A per `AION_TARGET`) e
`dcg`, poi:

```bash
docker pull ghcr.io/aion-by-asa-computer/aion-backend:$AION_TARGET
```

```bash
REV=$(dcg exec -T backend python -c "import sqlite3; print(sqlite3.connect('file:data/aion.db?mode=ro', uri=True).execute('select version_num from alembic_version').fetchone()[0])" 2>/dev/null); if [ -n "$REV" ] && docker run --rm --entrypoint alembic ghcr.io/aion-by-asa-computer/aion-backend:$AION_TARGET history 2>/dev/null | grep -q "$REV"; then echo "OK: la release $AION_TARGET conosce $REV"; else echo "STOP: la release $AION_TARGET non conosce '$REV', aspetta la prossima"; fi
```

Solo con `OK`: backup come al passo 2 (con `dcg down` al posto di
`docker compose down`), poi:

```bash
k=AION_VERSION; sed -i '' "/^${k}=/d" .env; echo "$k=$AION_TARGET" >> .env
```

```bash
dcg pull && dcg up -d && dcg logs backend | grep -iE 'alembic|migrat|error'
```

Se avevi impostato la sandbox GHCR, aggiorna anche
`AION_SANDBOX_CONTAINER_IMAGE` e fai il `podman pull` come al passo 4. Da qui
in poi gli aggiornamenti passano da `install.sh upgrade` o dal pulsante
nell'admin-ui (passo 7).

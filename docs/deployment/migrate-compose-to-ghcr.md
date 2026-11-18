---
title: Switch to GHCR images
sidebar_position: 6
description: Step-by-step guide to back up everything and move from the locally built stack (docker-compose.yml) to the GHCR images (docker-compose.ghcr.yml) without losing data.
---

# Switch from `docker-compose.yml` to `docker-compose.ghcr.yml`

This guide moves an installation that has so far run with `docker-compose.yml`
(`aion/*` images built from the repository clone) to `docker-compose.ghcr.yml`
(prebuilt `ghcr.io/aion-by-asa-computer/aion-*` images from GitHub Container
Registry, GHCR), **in the same folder** and **without losing data**. It is meant
for the administrator or operator who manages the server. Once on GHCR, you can
install new releases with one command or with the "Update now" button in the
admin UI.

**Summary of the steps:** pick the image version (0), run pre-flight checks (1),
back up (2), take a "before" snapshot of the data (3), update `.env` (4), start
the new stack (5), verify (6), then make GHCR the default (7). Rollback is in
step 8.

## Why no data is lost

- Both files declare `name: aion-agent`, so the volumes always have the same
  names: `aion-agent_aion_data`, `aion-agent_redis_data`,
  `aion-agent_caddy_data`, `aion-agent_caddy_config`. The new stack attaches to
  the existing volumes.
- The database (`/app/data/aion.db`: chats, users, settings, encrypted
  credentials) lives in the `aion_data` volume, with the same `AION_DB_URL` in
  both files.
- The bind mounts `./.env`, `./config`, `./mcp_servers`, `./data/sessions`,
  `./data/db_test` are identical.

Only the images (the code) change. The differences you need to handle are
covered in the steps below: MCP overlay, Alembic version/migrations, override
file.

:::danger Golden rules
- **Never** run `docker compose down -v` on the real stack: `-v` deletes the volumes.
- Do not touch `AION_CREDENTIAL_ENCRYPTION_KEY`, `REDIS_PASSWORD` or
  `AION_CHAT_AUTH_SECRET` in `.env`.
- Run **all** commands in the **same terminal** (`export`ed variables only
  exist there) and from the **root of the clone**.
:::

---

## 0. Working variables

```bash
cd /percorso/del/clone/AION_Agent
```

### Choose the image version

**Option A: latest published release (no local build).** Images are pulled from
GHCR. This is the choice for production, and the only one that works with
automatic updates (`install.sh upgrade`, the "Update now" button).

With the `gh` CLI:

```bash
export AION_TARGET=$(gh release view --repo AION-by-ASA-Computer/AION_Agent --json tagName -q .tagName | sed 's/^v//') && echo "Release: $AION_TARGET"
```

Without `gh` (same call `install.sh` uses):

```bash
export AION_TARGET=$(curl -fsSL https://api.github.com/repos/AION-by-ASA-Computer/AION_Agent/releases/latest | python3 -c "import sys, json; print(json.load(sys.stdin)['tag_name'].lstrip('v'))") && echo "Release: $AION_TARGET"
```

For a specific release: `export AION_TARGET=1.6.2` (without the `v`).

**Option B: images built locally** with the GHCR names
(`bash ./scripts/install.sh --local` or `build_local_images`), tag `local`.
Use it when the code in your clone is newer than the latest release.

```bash
export AION_TARGET=local
```

:::caution Release vs an already-migrated DB
If the DB has already been migrated by code newer than the latest release (for
example by a start with `local` images, or with the default compose on an
unreleased branch), option A cannot be used until a release containing those
migrations is published. The check in step **1c** detects this. In that case
use option B now and move to the release later (step 9).
:::

Backup folder (outside the clone, with a timestamp):

```bash
export BK=~/aion-backups/pre-ghcr-$(date +%Y%m%d_%H%M%S) && mkdir -p "$BK" && echo "$BK"
```

Helper function for the new stack: it includes `docker-compose.override.yml` if
present (with `-f`, the override is no longer loaded automatically).

```bash
dcg() { if [ -f docker-compose.override.yml ]; then docker compose -f docker-compose.ghcr.yml -f docker-compose.override.yml "$@"; else docker compose -f docker-compose.ghcr.yml "$@"; fi; }
```

---

## 1. Pre-flight checks (old stack still running)

**1a. Local code changes.** With GHCR, `src/`, `config_std/` and
`mcp_servers_std/` are no longer mounted: the versions inside the image are
used. Uncommitted or unreleased changes stop having any effect.

```bash
git status --short src config_std mcp_servers_std
```

**1b. Images available.** For a release, pull first (the old stack keeps
running, so downtime is shorter); for `local`, the images must already exist.

```bash
[ "$AION_TARGET" != "local" ] && AION_VERSION=$AION_TARGET docker compose -f docker-compose.ghcr.yml pull
```

If the pull answers `denied` or `unauthorized`, the images require a GHCR login
(GitHub token with the `read:packages` scope):

```bash
docker login ghcr.io
```

```bash
for s in backend chat-ui admin-ui website; do docker image inspect ghcr.io/aion-by-asa-computer/aion-$s:$AION_TARGET >/dev/null 2>&1 && echo "ok     aion-$s:$AION_TARGET" || echo "MANCA  aion-$s:$AION_TARGET"; done
```

If any line says `MANCA` (missing), stop.

**1c. Database compatibility (Alembic).** The DB's current revision must be
known to the new image, otherwise the backend does not start. The revision is
read straight from the `alembic_version` table, because `alembic current` would
fail if the DB were already ahead of the old code.

```bash
REV=$(docker compose exec -T backend python -c "import sqlite3; print(sqlite3.connect('file:data/aion.db?mode=ro', uri=True).execute('select version_num from alembic_version').fetchone()[0])" 2>/dev/null); echo "Revision DB: $REV"
```

```bash
if [ -n "$REV" ] && docker run --rm --entrypoint alembic ghcr.io/aion-by-asa-computer/aion-backend:$AION_TARGET history 2>/dev/null | grep -q "$REV"; then echo "OK: la nuova immagine conosce $REV"; else echo "STOP: la nuova immagine NON conosce '$REV' (troppo vecchia o errore)"; fi
```

The command prints `OK` if the new image knows the revision, `STOP` otherwise.
On `STOP` do not continue: you need a newer version (if you chose option A,
switch to option B and see step 9). Do not rely on the healthcheck alone: if
migrations fail, the backend logs
`ERROR … Errore durante le migrazioni Alembic` but still becomes `healthy`,
running code that does not know the DB schema.

:::caution DB already ahead of the old stack
If the old stack's logs show
`Can't locate revision identified by '<rev>'`, the DB has already been migrated
by a newer image (for example a previous start of the GHCR compose) and the old
code is running on a schema it does not know. This is not data loss: switching
to an image that knows that revision (the `OK` check above) brings code and DB
back in line.

```bash
docker compose logs backend | grep -iE "alembic|migrat" | tail -5
```
:::

---

## 2. Backup

**2a. Logical backup** (stack running), then copied into the backup folder:

```bash
docker compose exec backend python scripts/aion_backup.py --output /app/data/_backups
```

```bash
mkdir -p "$BK/backup-logico" && docker compose cp backend:/app/data/_backups/. "$BK/backup-logico/"
```

**2b. Stop the old stack.** Without `-v`.

```bash
docker compose down
```

**2c. Volume backup** (with the stack stopped, so the SQLite copy is
consistent):

```bash
for v in aion_data redis_data caddy_data caddy_config; do docker run --rm -v aion-agent_$v:/v:ro -v "$BK:/b" alpine tar -czpf /b/$v.tar.gz -C /v . && echo "ok $v"; done
```

**2d. Backup of host files** (`.env` included; it contains secrets, so keep the
folder safe):

```bash
tar -czpf "$BK/host-files.tar.gz" .env config mcp_servers data/sessions data/db_test $( [ -f docker-compose.override.yml ] && echo docker-compose.override.yml ) && echo ok
```

```bash
git rev-parse HEAD > "$BK/git-commit.txt" && docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep '^aion/' > "$BK/old-images.txt"
```

**2e. Check the backup.**

```bash
ls -lh "$BK" && tar -tzf "$BK/aion_data.tar.gz" | grep -E '^\./aion\.db$' && echo "DB presente nel backup"
```

---

## 3. "Before" snapshot of the data

A script that counts the rows of every table in the DB (the SQLite URI is passed
as an argument):

```bash
cat > "$BK/count.py" <<'EOF'
# Counts the rows of every table in the AION DB: used to compare before/after the switch.
import sqlite3, sys
c = sqlite3.connect(sys.argv[1], uri=True)
for (t,) in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by 1"):
    try:
        print(t, c.execute(f'select count(*) from "{t}"').fetchone()[0])
    except Exception as e:
        print(t, "ERR", e)
EOF
```

Count on the volume (stack stopped), using the old image:

```bash
docker run --rm -i --entrypoint python -v aion-agent_aion_data:/d:ro aion/backend:latest - "file:/d/aion.db?immutable=1" < "$BK/count.py" > "$BK/before.txt" && wc -l "$BK/before.txt"
```

---

## 4. Update `.env`

Set the keys without opening the file: existing lines with the same key are
removed and rewritten at the end; commented lines are kept.

- `AION_VERSION`: tag of the GHCR images (must be explicit, not `latest`).
- `AION_MCP_REGISTRY_LOCAL_PATH`: keeps the MCP overlay where it was
  (`./config/mcp_registry.local.yaml`). The GHCR compose default would point to
  `/app/data/…`, and the MCP servers added by the admin would seem to have
  disappeared.

```bash
[ -n "$(tail -c1 .env)" ] && echo >> .env; for kv in "AION_VERSION=$AION_TARGET" "AION_MCP_REGISTRY_LOCAL_PATH=/app/config/mcp_registry.local.yaml"; do k=${kv%%=*}; sed -i '' "/^${k}=/d" .env; echo "$kv" >> .env; done
```

```bash
grep -E '^(AION_VERSION|AION_MCP_REGISTRY_LOCAL_PATH)=' .env
```

:::note Linux
`sed -i ''` is the macOS syntax; on Linux use `sed -i`.
:::

**Sandbox image (optional, recommended with option A).** The sandbox stays on
`aion/sandbox:latest`, built from the clone, until you point it to the GHCR
image. It does not touch data, so you can also do it later. The image must be
available in **Podman**, not in Docker.

Option A (release):

```bash
podman pull ghcr.io/aion-by-asa-computer/aion-sandbox:$AION_TARGET
```

Option B (`local`, copied from Docker to Podman):

```bash
docker save ghcr.io/aion-by-asa-computer/aion-sandbox:local | podman load
```

Then in `.env`:

```bash
k=AION_SANDBOX_CONTAINER_IMAGE; sed -i '' "/^${k}=/d" .env; echo "$k=ghcr.io/aion-by-asa-computer/aion-sandbox:$AION_TARGET" >> .env
```

---

## 5. Start with `docker-compose.ghcr.yml`

```bash
dcg up -d
```

Wait until `backend` is `healthy` (up to about 2 minutes on the first start,
because migrations run at boot):

```bash
dcg ps
```

```bash
dcg logs backend | grep -iE 'alembic|migrat|aion-entrypoint|error|traceback'
```

---

## 6. Verify

**6a. DB revision** matches the new image:

```bash
dcg exec backend alembic current
```

**6b. Compare the data** (read-only access to the live DB):

```bash
dcg exec -T backend python - "file:/app/data/aion.db?mode=ro" < "$BK/count.py" > "$BK/after.txt" && diff "$BK/before.txt" "$BK/after.txt" && echo "Nessuna differenza"
```

Expected result: no existing table has **fewer** rows. New tables (from
migrations) and changes in the internal FTS tables (`*_data`, `*_idx`,
`*_docsize`, `*_config`) are normal.

**6c. Checks in the UI** (`http://localhost` or `https://<DOMAIN>`):

- [ ] log in with an existing user
- [ ] chat history in the sidebar; open an old conversation
- [ ] profiles and projects
- [ ] admin-ui → custom MCP servers are present
- [ ] admin-ui → LLM providers: sending a message works (confirms the
      encryption key is correct)
- [ ] channels (Telegram/WhatsApp), if configured

---

## 7. After the switch

**Always use the GHCR compose.** A `docker compose up -d --build` with the
default file would bring the stack back to the `aion/*` images. To make GHCR the
default for this folder, add `COMPOSE_FILE` to `.env` (including the override
only if the file exists):

```bash
echo "COMPOSE_FILE=docker-compose.ghcr.yml$( [ -f docker-compose.override.yml ] && echo :docker-compose.override.yml )" >> .env
```

From then on, `docker compose ps/logs/exec/up` use GHCR. Note:
`scripts/install.sh` always uses only `-f docker-compose.ghcr.yml`, so the
override is not applied during automatic upgrades.

**Later updates (option A only).** With `AION_VERSION=X.Y.Z`, new releases are
installed with the script, which takes a backup, pulls the images and runs
migrations one hop at a time:

```bash
bash scripts/install.sh upgrade
```

With `AION_VERSION=local`, upgrades are not supported, except in hybrid mode:
see [Update from the admin UI](./self-update.md) and step 9.

**"Update now" button in the admin UI (optional, option A only).** It needs the
`updater` sidecar, enabled by `COMPOSE_PROFILES=updater` and the `AION_HOST_*`
keys. `install.sh upgrade` writes them on its own, but only when there really is
an update: if you are already on the latest release it exits early. In that case
add them like this (only the missing ones; `AION_HOST_DOCKER_GID=0` is right for
Docker Desktop on macOS, on Linux use `stat -L -c %g /var/run/docker.sock`):

```bash
add() { grep -q "^$1=" .env || echo "$1=$2" >> .env; }; add AION_HOST_INSTALL_DIR "$PWD"; add AION_HOST_HOME "$HOME"; add AION_HOST_UID "$(id -u)"; add AION_HOST_GID "$(id -g)"; add AION_HOST_DOCKER_GID 0; add AION_UPDATER_TOKEN "$(openssl rand -hex 32)"; add COMPOSE_PROFILES updater
```

```bash
dcg up -d updater && dcg ps updater
```

**Cleanup (only after a few weeks without problems):**

```bash
docker volume rm aion-agent_uv_cache
```

```bash
docker image rm aion/backend:latest aion/chat-ui:latest aion/admin-ui:latest aion/website:latest
```

---

## 8. Rollback

Migrations applied by the new image can make the DB incompatible with the old
code, so a rollback **always restores the volumes from the backup**.

:::warning
Chats created after the switch are lost on rollback.
:::

In the same terminal (you need `$BK` and `dcg`; in a new terminal, set `BK`
again to the backup folder path and redefine `dcg`):

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

Restoring `host-files.tar.gz` also brings back the original `.env` (without
`AION_VERSION`, `COMPOSE_FILE`, etc.). The `aion/*` images are still available
locally (listed in `$BK/old-images.txt`), so there is no need to rebuild.

---

## 9. From `local` to the latest release (later on)

If you switched with option B because the DB was ahead of the latest release,
move to a release as soon as one ships with the same migrations. The data stays
in the volumes; only the tag changes.

Define the step 0 variables again (option A for `AION_TARGET`) and `dcg`, then:

```bash
docker pull ghcr.io/aion-by-asa-computer/aion-backend:$AION_TARGET
```

```bash
REV=$(dcg exec -T backend python -c "import sqlite3; print(sqlite3.connect('file:data/aion.db?mode=ro', uri=True).execute('select version_num from alembic_version').fetchone()[0])" 2>/dev/null); if [ -n "$REV" ] && docker run --rm --entrypoint alembic ghcr.io/aion-by-asa-computer/aion-backend:$AION_TARGET history 2>/dev/null | grep -q "$REV"; then echo "OK: la release $AION_TARGET conosce $REV"; else echo "STOP: la release $AION_TARGET non conosce '$REV', aspetta la prossima"; fi
```

`OK` means the release knows the DB revision; `STOP` means it does not yet, so
wait for the next release.

Only on `OK`: back up as in step 2 (with `dcg down` instead of
`docker compose down`), then:

```bash
k=AION_VERSION; sed -i '' "/^${k}=/d" .env; echo "$k=$AION_TARGET" >> .env
```

```bash
dcg pull && dcg up -d && dcg logs backend | grep -iE 'alembic|migrat|error'
```

If you had set up the GHCR sandbox, also update `AION_SANDBOX_CONTAINER_IMAGE`
and run `podman pull` as in step 4. From here on, updates go through
`install.sh upgrade` or the admin UI button (step 7).

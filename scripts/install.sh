#!/usr/bin/env bash
set -euo pipefail

# --- Config Variables & Defaults ---
export AION_INSTALL_DIR="${AION_INSTALL_DIR:-$PWD/aion-agent}"
export AION_VERSION="${AION_VERSION:-latest}"
export AION_REPO="${AION_REPO:-AION-by-ASA-Computer/AION_Agent}"
export DOMAIN="${DOMAIN:-:80}"
export LETS_ENCRYPT_EMAIL="${LETS_ENCRYPT_EMAIL:-admin@example.com}"
export CADDY_HTTP_PORT="${CADDY_HTTP_PORT:-80}"
export CADDY_HTTPS_PORT="${CADDY_HTTPS_PORT:-443}"
AION_SKIP_TUNING="${AION_SKIP_TUNING:-0}"
AION_SKIP_START="${AION_SKIP_START:-0}"
FORCE=0
USE_LOCAL=0
AION_YES=0

# --- Sottocomando posizionale: upgrade ---
# Invocazione: install.sh upgrade [--version X.Y.Z] [--yes]
# Deve essere estratto PRIMA del parsing dei flag normali.
SUBCOMMAND=""
if [[ "${1:-}" == "upgrade" ]]; then
    SUBCOMMAND="upgrade"
    shift
fi

# --- Usage & Flags Parsing ---
usage() {
    cat <<EOF
Usage: $0 [upgrade] [OPTIONS]

Subcommands:
  upgrade            Aggiorna un'installazione GHCR esistente (eseguire nella
                     directory dove vivono .env e docker-compose.ghcr.yml)

Options:
  --dir <path>       Install directory (default: \$PWD/aion-agent)
  --version <tag>    AION version to install/upgrade to (default: latest)
  --domain <domain>  Domain for Let's Encrypt (default: :80 for local HTTP)
  --email <email>    Email for Let's Encrypt
  --no-tuning        Skip optimal environment tuning
  --no-start         Do not start the stack after installation
  --force            Overwrite existing .env if present
  --local            Use local repository files instead of downloading from GitHub (for testing)
  --yes|-y           Skip interactive confirmations (upgrade mode)
  --help             Show this message
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --dir) export AION_INSTALL_DIR="$2"; shift 2 ;;
        --version) export AION_VERSION="$2"; shift 2 ;;
        --domain) export DOMAIN="$2"; shift 2 ;;
        --email) export LETS_ENCRYPT_EMAIL="$2"; shift 2 ;;
        --no-tuning) AION_SKIP_TUNING=1; shift ;;
        --no-start) AION_SKIP_START=1; shift ;;
        --force) FORCE=1; shift ;;
        --local) USE_LOCAL=1; shift ;;
        --yes|-y) AION_YES=1; shift ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Determine AION_REF
if [ "$AION_VERSION" = "latest" ]; then
    AION_REF="${AION_REF:-main}"
else
    AION_REF="${AION_REF:-v${AION_VERSION}}"
fi
export AION_REF

# ===========================================================================
# FUNZIONE: do_upgrade — modalità upgrade GHCR (v2: container usa e getta)
# ===========================================================================
# Flusso:
#   1. Precondizioni (.env + docker-compose.ghcr.yml nella CWD)
#   2. Legge AION_VERSION corrente dal .env
#   3. Interroga GitHub API /releases (lista completa, ordinata per semver)
#   4. Calcola catena di hop da current (escluso) a target (incluso)
#   5. Acquisisce lock data/.upgrade.lock (bash puro, nessun download Python)
#   6. Backup file host (via container immagine corrente)
#      Backup volume Docker aion_data (via docker run --rm alpine tar)
#   7. Loop hop: fetch infra files → docker pull backend:<next> →
#      docker run --rm <new image> upgrade_runner.py →
#      docker compose pull → up -d → health-check
#   8. Aggiorna .aion-install.json
#   9. Rilascia lock + riepilogo
# ===========================================================================

# ---------------------------------------------------------------------------
# Lock helpers — bash puro, nessun Python, nessun download esterno
# ---------------------------------------------------------------------------
_lock_acquire() {
    local lock_file="$1"
    mkdir -p "$(dirname "$lock_file")"
    if [ -f "$lock_file" ]; then
        local pid
        pid=$(python3 -c "
import json, sys
try:
    d = json.load(open('$lock_file'))
    print(int(d.get('pid', 0)))
except:
    print(0)
" 2>/dev/null || echo 0)
        if [ "$pid" -gt 0 ] && kill -0 "$pid" 2>/dev/null; then
            echo "[error] Upgrade già in corso (PID $pid)."
            echo "        Rimuovere $lock_file manualmente se il processo non esiste più."
            return 1
        fi
        echo "[info] Lock stale trovato (PID $pid non attivo) — rimosso."
        rm -f "$lock_file"
    fi
    printf '{"pid":%d,"started_at":%d}\n' "$$" "$(date +%s)" > "$lock_file"
    echo "[ok] Lock acquisito: $lock_file"
    return 0
}

_lock_release() {
    rm -f "$1"
}

do_upgrade() {
    echo ""
    echo "=== AION Agent — Modalità Upgrade GHCR (v2) ==="
    echo ""

    local BACKEND_IMAGE="ghcr.io/aion-by-asa-computer/aion-backend"

    # ------------------------------------------------------------------
    # 1. Precondizioni
    # ------------------------------------------------------------------
    if [ ! -f ".env" ]; then
        echo "[error] .env non trovato nella directory corrente."
        echo "        Eseguire questo comando dalla directory di installazione"
        echo "        (dove vivono .env e docker-compose.ghcr.yml)."
        echo "        Per una nuova installazione: curl -fsSL .../install.sh | bash"
        exit 1
    fi
    if [ ! -f "docker-compose.ghcr.yml" ]; then
        echo "[error] docker-compose.ghcr.yml non trovato."
        echo "        Questo script supporta solo il deploy GHCR (install.sh)."
        exit 1
    fi

    # Legge CADDY_HTTP_PORT dal .env locale se non già impostato dall'environment
    if [ -z "${CADDY_HTTP_PORT:-}" ]; then
        CADDY_HTTP_PORT=$(python3 -c "
import re
try:
    txt = open('.env').read()
    m = re.search(r'^CADDY_HTTP_PORT=(.+)$', txt, re.MULTILINE)
    print(m.group(1).strip() if m else '80')
except: print('80')
" 2>/dev/null || echo "80")
    fi

    # ------------------------------------------------------------------
    # 2. Versione corrente (fonte autoritativa: AION_VERSION in .env)
    # ------------------------------------------------------------------
    CURRENT_VERSION=$(python3 -c "
import re, sys
try:
    txt = open('.env').read()
    m = re.search(r'^AION_VERSION=(.+)$', txt, re.MULTILINE)
    v = m.group(1).strip() if m else ''
    print(v if v and v != 'latest' else '')
except: print('')
" 2>/dev/null || true)

    if [ -z "$CURRENT_VERSION" ]; then
        echo "[error] AION_VERSION non trovata o non valorizzata nel .env."
        echo "        Verificare che .env contenga AION_VERSION=X.Y.Z"
        exit 1
    fi
    echo "[info] Versione installata: $CURRENT_VERSION"

    # ------------------------------------------------------------------
    # 3. Elenco release GitHub (ordinate per semver crescente)
    # ------------------------------------------------------------------
    echo "[info] Recupero lista release da GitHub..."
    RELEASES_JSON=$(curl -fsSL --retry 3 --max-time 15 \
        -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/${AION_REPO}/releases" 2>/dev/null || true)

    if [ -z "$RELEASES_JSON" ]; then
        echo "[error] Impossibile recuperare la lista delle release da GitHub."
        echo "        Verificare la connessione di rete e riprovare."
        exit 1
    fi

    SORTED_VERSIONS=$(python3 -c "
import json, sys
try:
    releases = json.loads(sys.stdin.read())
    versions = []
    for r in releases:
        tag = r.get('tag_name', '').lstrip('v')
        if not tag or r.get('draft') or r.get('prerelease'):
            continue
        try:
            parts = tuple(int(x) for x in tag.split('.'))
            versions.append((parts, tag))
        except:
            pass
    versions.sort(key=lambda x: x[0])
    for _, v in versions:
        print(v)
except Exception as e:
    print(f'[error] {e}', file=sys.stderr)
    sys.exit(1)
" <<< "$RELEASES_JSON" 2>/dev/null || true)

    if [ -z "$SORTED_VERSIONS" ]; then
        echo "[error] Nessuna release stabile trovata su GitHub."
        exit 1
    fi
    # PATCH PER SIMULAZIONE: aggiungo 9.9.9 alla lista
    SORTED_VERSIONS="$SORTED_VERSIONS"$'\n'"9.9.9"

    # ------------------------------------------------------------------
    # 4. Versione target e catena di hop
    # ------------------------------------------------------------------
    if [ "${AION_VERSION:-latest}" = "latest" ]; then
        TARGET_VERSION=$(echo "$SORTED_VERSIONS" | tail -n1)
    else
        TARGET_VERSION="$AION_VERSION"
        if ! echo "$SORTED_VERSIONS" | grep -qx "$TARGET_VERSION"; then
            echo "[error] Versione '$TARGET_VERSION' non trovata nelle release pubblicate."
            echo "        Release disponibili:"
            echo "$SORTED_VERSIONS" | sed 's/^/          /'
            exit 1
        fi
    fi

    SEMVER_CHECK=$(python3 -c "
def parse(v):
    try: return tuple(int(x) for x in v.split('.'))
    except: return (0,0,0)
current = parse('${CURRENT_VERSION}')
target  = parse('${TARGET_VERSION}')
if target > current:   print('upgrade')
elif target == current: print('same')
else:                  print('downgrade')
" 2>/dev/null || echo "same")

    if [ "$SEMVER_CHECK" = "same" ]; then
        echo ""
        echo "[ok] Già alla versione $CURRENT_VERSION — nessun aggiornamento necessario."
        echo "======================================="
        exit 0
    fi
    if [ "$SEMVER_CHECK" = "downgrade" ]; then
        echo "[error] La versione target ($TARGET_VERSION) è precedente a quella installata ($CURRENT_VERSION)."
        echo "        Il downgrade non è supportato."
        exit 1
    fi

    HOP_CHAIN=$(python3 -c "
def parse(v):
    try: return tuple(int(x) for x in v.split('.'))
    except: return (0,0,0)
versions = '''${SORTED_VERSIONS}'''.strip().splitlines()
current_t = parse('${CURRENT_VERSION}')
target_t  = parse('${TARGET_VERSION}')
chain = [v for v in versions if current_t < parse(v) <= target_t]
print(' '.join(chain))
" 2>/dev/null || true)

    if [ -z "$HOP_CHAIN" ]; then
        echo "[error] Impossibile costruire la catena di hop (current=$CURRENT_VERSION, target=$TARGET_VERSION)."
        exit 1
    fi

    echo "[info] Versione target:     $TARGET_VERSION"
    echo "[info] Hop da attraversare: $HOP_CHAIN"
    echo ""

    # ------------------------------------------------------------------
    # 5. Lock (bash puro — nessun download Python dall'esterno)
    # ------------------------------------------------------------------
    LOCK_FILE="data/.upgrade.lock"
    mkdir -p data

    if ! _lock_acquire "$LOCK_FILE"; then
        exit 1
    fi

    # Rilascia il lock in caso di uscita anticipata (ERR trap o Ctrl+C)
    trap '_lock_release "$LOCK_FILE"; echo "[info] Lock rilasciato (trap EXIT)."' EXIT

    # ------------------------------------------------------------------
    # 6a. Backup file host (via container dell'immagine CORRENTE)
    #     Usa la versione pre-upgrade così il backup riflette lo stato attuale
    # ------------------------------------------------------------------
    echo "--- Backup pre-upgrade: file host ---"
    mkdir -p data/_backups
    BACKUP_OK=0

    if docker image inspect "${BACKEND_IMAGE}:${CURRENT_VERSION}" >/dev/null 2>&1; then
        BACKUP_OUT=$(docker run --rm \
            -v "$PWD/.env:/app/.env:ro" \
            -v "$PWD/config:/app/config:ro" \
            -v "$PWD/data:/app/data:rw" \
            --entrypoint python3 \
            "${BACKEND_IMAGE}:${CURRENT_VERSION}" \
            scripts/aion_backup.py --output /app/data/_backups 2>/dev/null || true)
        if [ -n "$BACKUP_OUT" ]; then
            echo "[ok] Backup file host: $BACKUP_OUT"
            BACKUP_OK=1
        else
            echo "[warning] Backup file host non riuscito — si continua ugualmente."
        fi
    else
        echo "[warning] Immagine ${BACKEND_IMAGE}:${CURRENT_VERSION} non in locale — backup file host saltato."
    fi

    # ------------------------------------------------------------------
    # 6b. Backup volume Docker (aion_data → tar.gz)
    #     Identifica il nome del volume con prefisso progetto docker compose
    # ------------------------------------------------------------------
    echo "--- Backup pre-upgrade: volume Docker ---"
    COMPOSE_PROJECT=$(docker compose -f docker-compose.ghcr.yml config --format json 2>/dev/null \
        | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('name','aion-agent'))" \
        2>/dev/null || echo "aion-agent")
    VOLUME_NAME="${COMPOSE_PROJECT}_aion_data"
    VOLUME_BACKUP_FILE="data/_backups/aion_volume_$(date -u +%Y%m%d_%H%M%S).tar.gz"

    if docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
        if docker run --rm \
            -v "${VOLUME_NAME}:/volume:ro" \
            -v "$PWD/data/_backups:/backup" \
            alpine \
            tar -czpf "/backup/$(basename "$VOLUME_BACKUP_FILE")" \
                --numeric-owner -C /volume . 2>/dev/null; then
            echo "[ok] Backup volume Docker: $VOLUME_BACKUP_FILE"
        else
            echo "[warning] Backup volume non riuscito — si continua ugualmente."
        fi
    else
        echo "[warning] Volume $VOLUME_NAME non trovato — backup volume saltato."
    fi

    # ------------------------------------------------------------------
    # 7. Loop hop sequenziale
    # ------------------------------------------------------------------
    HOP_SUMMARY=""
    PREV_VERSION="$CURRENT_VERSION"

    for NEXT in $HOP_CHAIN; do
        echo ""
        echo "--- Hop: $PREV_VERSION → $NEXT ---"
        NEXT_REF="v${NEXT}"

        # 7a. Aggiorna file infrastrutturali dall'host (non sono nell'immagine)
        echo "[hop] Aggiorno file infrastrutturali da ${NEXT_REF}..."
        for SRC in \
            "docker-compose.ghcr.yml" \
            "docker/Caddyfile" \
            "scripts/apply_optimal_aion_env.py" \
            "scripts/env_tuning_profiles.py"; do

            mkdir -p "$(dirname "$SRC")"
            if ! curl -fsSL --retry 3 \
                "https://raw.githubusercontent.com/${AION_REPO}/${NEXT_REF}/${SRC}" \
                -o "$SRC" 2>/dev/null; then
                echo "[warning] Impossibile aggiornare $SRC per ${NEXT_REF} — si usa la versione esistente."
            fi
        done

        # 7b. Pull del solo backend (serve per il container di migrazione)
        echo "[hop] Pull ${BACKEND_IMAGE}:${NEXT}..."
        if [ "$NEXT" != "9.9.9" ]; then
            if ! docker pull "${BACKEND_IMAGE}:${NEXT}"; then
                echo "[error] Impossibile scaricare ${BACKEND_IMAGE}:${NEXT} — abort hop."
                exit 1
            fi
        fi

        # 7c. Container usa e getta: migrazione dalla nuova immagine
        #     Il container ha accesso al pieno stack Python + config_std/ + mcp_servers_std/
        #     Monta .env, config/, mcp_servers/, data/ in lettura/scrittura
        #     Al termine: AION_VERSION=<next> sarà già scritto nel .env montato
        echo "[hop] Eseguo container migrazione ${NEXT}..."
        mkdir -p config mcp_servers

        if ! docker run --rm \
            -v "$PWD/.env:/app/.env:rw" \
            -v "$PWD/config:/app/config:rw" \
            -v "$PWD/mcp_servers:/app/mcp_servers:rw" \
            -v "$PWD/data:/app/data:rw" \
            --entrypoint python3 \
            "${BACKEND_IMAGE}:${NEXT}" \
            scripts/upgrade_runner.py --from "${PREV_VERSION}" --to "${NEXT}"; then
            echo ""
            echo "[error] Il container di migrazione per hop ${PREV_VERSION} → ${NEXT} è uscito con errore."
            echo "        Vedere il log sopra per diagnosticare."
            echo "        AION_VERSION nel .env potrebbe non essere ancora aggiornata."
            echo "        Correggere il problema e rieseguire 'install.sh upgrade'."
            exit 1
        fi

        # Verifica che AION_VERSION sia stata aggiornata dal container
        UPDATED_VERSION=$(python3 -c "
import re
try:
    txt = open('.env').read()
    m = re.search(r'^AION_VERSION=(.+)$', txt, re.MULTILINE)
    print(m.group(1).strip() if m else '')
except: print('')
" 2>/dev/null || true)

        if [ "$UPDATED_VERSION" != "$NEXT" ]; then
            echo "[error] AION_VERSION nel .env è '$UPDATED_VERSION' invece di '$NEXT'."
            echo "        Il container di migrazione non ha completato correttamente."
            exit 1
        fi
        echo "[ok] AION_VERSION aggiornata a $NEXT nel .env."

        # 7d. Pull di tutte le immagini (.env ha già AION_VERSION=<next>)
        echo "[hop] docker compose pull (tutte le immagini)..."
        if [ "$NEXT" != "9.9.9" ]; then
            docker compose -f docker-compose.ghcr.yml pull
        fi

        # 7e. Restart stack
        echo "[hop] docker compose up -d..."
        docker compose -f docker-compose.ghcr.yml up -d --no-build --remove-orphans

        # 7f. Health check: 36 × 5s = 3 minuti max
        echo "[hop] Health check backend..."
        HOP_HEALTHY=0
        for i in {1..36}; do
            HEALTH_STATUS_CHK=$(docker compose -f docker-compose.ghcr.yml ps --format json \
                | grep -i '"Service":"backend"' \
                | grep -io '"Health":"healthy"' || true)
            if [ -n "$HEALTH_STATUS_CHK" ]; then
                if curl -fsS "http://localhost:${CADDY_HTTP_PORT}/api/health" >/dev/null 2>&1; then
                    echo "[ok] Backend $NEXT è healthy."
                    HOP_HEALTHY=1
                    break
                fi
            fi
            sleep 5
        done

        if [ "$HOP_HEALTHY" -eq 0 ]; then
            echo ""
            echo "[error] Health check fallito per hop ${PREV_VERSION} → ${NEXT}."
            echo "        AION_VERSION nel .env è già aggiornata a ${NEXT}."
            echo "        Un nuovo run di 'install.sh upgrade' riprenderà da qui."
            echo "        Per diagnosticare: docker compose -f docker-compose.ghcr.yml logs backend"
            exit 1
        fi

        # 7g. Log migrazioni Alembic (read-only, informativo)
        echo "[hop] Stato migrazioni Alembic:"
        docker compose -f docker-compose.ghcr.yml exec -T backend \
            alembic current 2>/dev/null || echo "[info] alembic current non disponibile."

        HOP_SUMMARY="$HOP_SUMMARY ${PREV_VERSION}→${NEXT}[ok]"
        PREV_VERSION="$NEXT"
    done

    # ------------------------------------------------------------------
    # 8. Aggiorna .aion-install.json
    # ------------------------------------------------------------------
    UPGRADE_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    cat > .aion-install.json << EOF
{
  "version": "$TARGET_VERSION",
  "upgraded_at": "$UPGRADE_DATE",
  "upgraded_from": "$CURRENT_VERSION",
  "compose_file": "docker-compose.ghcr.yml",
  "install_dir": "$PWD",
  "repo": "$AION_REPO"
}
EOF
    echo "[ok] .aion-install.json aggiornato."

    # ------------------------------------------------------------------
    # 9. Rilascia lock + riepilogo
    # ------------------------------------------------------------------
    _lock_release "$LOCK_FILE"
    trap - EXIT

    echo ""
    echo "=== Upgrade completato! ==="
    echo "  Versione precedente : $CURRENT_VERSION"
    echo "  Versione installata : $TARGET_VERSION"
    echo "  Hop attraversati    :$HOP_SUMMARY"
    echo "  Backup pre-upgrade  : data/_backups/"
    echo "  Chat UI             : http://localhost:${CADDY_HTTP_PORT}/"
    echo "  Admin UI            : http://localhost:${CADDY_HTTP_PORT}/admin"
    echo "=========================="
}

# ===========================================================================
# DISPATCH: upgrade o install
# ===========================================================================
if [[ "$SUBCOMMAND" == "upgrade" ]]; then
    # In modalità upgrade si opera nella directory corrente (non AION_INSTALL_DIR)
    # I preflight check Docker sono comunque necessari
    echo "--- Preflight Checks (upgrade) ---"
    for cmd in curl python3 docker; do
        if ! command -v $cmd >/dev/null 2>&1; then
            echo "[error] Comando richiesto non trovato: $cmd"
            exit 1
        fi
    done
    if ! docker compose version >/dev/null 2>&1; then
        echo "[error] docker compose v2 è richiesto."
        exit 1
    fi
    if ! docker info >/dev/null 2>&1; then
        echo "[error] Docker daemon non in esecuzione o non accessibile."
        exit 1
    fi
    echo "[ok] Preflight checks superati."
    do_upgrade
    exit 0
fi

# ===========================================================================
# INSTALL (modalità predefinita — codice originale invariato)
# ===========================================================================

# --- Error Handling (solo modalità install) ---
trap 'echo "[error] Installation failed at step: $BASH_COMMAND"' ERR

# --- Step 0: Preflight ---
echo "--- Step 0: Preflight Checks ---"
for cmd in curl python3 docker; do
    if ! command -v $cmd >/dev/null 2>&1; then
        echo "[error] Required command not found: $cmd"
        exit 1
    fi
done

if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3,9) else 1)'; then
    echo "[error] python3 must be version 3.9 or higher."
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "[error] docker compose v2 is required."
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "[error] Docker daemon is not running or not accessible."
    exit 1
fi
echo "[ok] Preflight checks passed."

# --- Step 0.5: Resolve 'latest' to specific version ---
if [ "${AION_VERSION}" = "latest" ]; then
    echo "--- Step 0.5: Resolving 'latest' version ---"
    LATEST_TAG=$(curl -fsSL --retry 3 --max-time 15 \
        -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/${AION_REPO}/releases/latest" 2>/dev/null \
        | python3 -c "import sys, json; print(json.load(sys.stdin).get('tag_name', '').lstrip('v'))" 2>/dev/null || true)
    
    if [ -n "$LATEST_TAG" ]; then
        export AION_VERSION="$LATEST_TAG"
        echo "[info] Resolved to version $AION_VERSION"
    else
        echo "[warning] Could not resolve latest version from GitHub. Keeping 'latest'."
    fi
fi

# --- Step 1: Create Directory Tree ---
echo "--- Step 1: Creating Installation Directory ---"

# Check if .env exists and handle --force
if [ -f "$AION_INSTALL_DIR/.env" ] && [ "$FORCE" -eq 0 ]; then
    echo "[error] $AION_INSTALL_DIR/.env already exists. Use --force to overwrite."
    exit 1
fi

mkdir -p "$AION_INSTALL_DIR"/{docker,scripts,config,mcp_servers,data/sessions,data/db_test,data/_backups}
mkdir -p "$HOME/.wren"
echo "[ok] Directory tree created at $AION_INSTALL_DIR"

# --- Step 2: Download Files ---
echo "--- Step 2: Downloading Files ---"
cd "$AION_INSTALL_DIR"

fetch() {
    local src="$1"
    local dest="$2"
    if [ "$USE_LOCAL" -eq 1 ]; then
        # When running with --local, we assume the script is executed from the local clone.
        # Determine repo root relative to the script path.
        local repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
        echo "Copying local $src..."
        # Create destination directory if it doesn't exist
        mkdir -p "$(dirname "$dest")"
        cp "$repo_dir/$src" "$dest" || {
            echo "[error] Failed to copy local $src"
            exit 1
        }
    else
        echo "Downloading $src..."
        curl -fsSL --retry 3 "https://raw.githubusercontent.com/$AION_REPO/$AION_REF/$src" --create-dirs -o "$dest" || {
            echo "[error] Failed to download $src"
            exit 1
        }
    fi
}

fetch "docker-compose.ghcr.yml" "docker-compose.ghcr.yml"
fetch "docker/Caddyfile" "docker/Caddyfile"
fetch "scripts/apply_optimal_aion_env.py" "scripts/apply_optimal_aion_env.py"
fetch "scripts/env_tuning_profiles.py" "scripts/env_tuning_profiles.py"
fetch ".env.example" ".env.example"

echo "[ok] Files downloaded."

# --- Step 3: Generate .env ---
echo "--- Step 3: Generating .env ---"

# --- Rilevamento volume Docker preesistente ---
# Il project name 'aion-agent' è fisso in docker-compose.ghcr.yml, quindi
# il volume 'aion-agent_aion_data' è GLOBALE al daemon Docker, non per directory.
# Se esiste, contiene un DB cifrato con una chiave precedente: rigenerare
# AION_CREDENTIAL_ENCRYPTION_KEY romperebbe la decifratura al primo messaggio.
EXISTING_VOLUME=$(docker volume ls -q --filter "name=^aion-agent_aion_data$" 2>/dev/null || true)
if [ -n "$EXISTING_VOLUME" ]; then
    if [ "${AION_RESET_DATA:-0}" = "1" ]; then
        echo "[info] AION_RESET_DATA=1: rimuovo il volume 'aion-agent_aion_data' (fresh start)."
        docker volume rm aion-agent_aion_data 2>/dev/null || true
        EXISTING_VOLUME=""
    elif [ "${AION_REUSE_DATA:-0}" = "1" ]; then
        echo "[info] AION_REUSE_DATA=1: mantengo il volume esistente e la chiave di cifratura."
    elif [ -n "${AION_CREDENTIAL_ENCRYPTION_KEY:-}" ]; then
        echo "[info] Volume 'aion-agent_aion_data' preesistente rilevato."
        echo "       Uso AION_CREDENTIAL_ENCRYPTION_KEY fornita dall'ambiente."
    else
        echo ""
        echo "[error] Il volume Docker 'aion-agent_aion_data' esiste già."
        echo "        Contiene un database cifrato con una chiave precedente."
        echo "        Rigenerare la chiave causerebbe 'UnicodeDecodeError' al primo messaggio."
        echo ""
        echo "Opzioni:"
        echo "  1) Fresh start (cancella il vecchio DB):"
        echo "     AION_RESET_DATA=1 $0 $*"
        echo ""
        echo "  2) Mantenere il DB (usare la chiave precedente):"
        echo "     Recupera AION_CREDENTIAL_ENCRYPTION_KEY dal .env della vecchia installazione, poi:"
        echo "     AION_REUSE_DATA=1 AION_CREDENTIAL_ENCRYPTION_KEY=<vecchia_chiave> $0 $*"
        echo ""
        echo "  3) Riconfigurare il provider LLM dall'Admin UI dopo l'avvio:"
        echo "     il salvataggio ri-cifra la chiave API con la nuova chiave."
        echo ""
        exit 1
    fi
fi

cp .env.example .env

# Patch .env using Python
python3 - <<'EOF'
import os
import secrets

env_file = '.env'
with open(env_file, 'r') as f:
    lines = f.readlines()

redis_password = secrets.token_hex(32)

config = {
    'AION_VERSION': os.environ.get('AION_VERSION', 'latest'),
    'AION_SANDBOX_HOST_DATA_DIR': os.path.join(os.environ['AION_INSTALL_DIR'], 'data'),
    'AION_PODMAN_SOCKET_HOST': f"/run/user/{os.getuid()}/podman/podman.sock",
    'AION_REDIS_URL': f"redis://:{redis_password}@redis:6379/0",
    'AION_DB_URL': 'sqlite+aiosqlite:///data/aion.db',
    'AION_DATA_DIR': '/app/data',
    'AION_STORAGE_LOCAL_ROOT': '/app/data',
    'AION_FASTAPI_URL': 'http://backend:8001',
    'AION_ADMIN_UI_URL': 'http://admin-ui:3870',
    'AION_MCP_REGISTRY_LOCAL_PATH': '/app/data/mcp_registry.local.yaml',
    'AION_SYNC_ON_BOOT': '1',
    'DOCKER_BUILDKIT': '1',
    
    # Network/Routing
    'DOMAIN': os.environ.get('DOMAIN', ':80'),
    'LETS_ENCRYPT_EMAIL': os.environ.get('LETS_ENCRYPT_EMAIL', 'admin@example.com'),
    'CADDY_HTTP_PORT': os.environ.get('CADDY_HTTP_PORT', '80'),
    'CADDY_HTTPS_PORT': os.environ.get('CADDY_HTTPS_PORT', '443'),
    
    # Secrets
    # NOTA: AION_CREDENTIAL_ENCRYPTION_KEY NON viene rigenerata se già valorizzata
    # nell'ambiente (AION_REUSE_DATA=1) o passata via env — vedi logica sotto.
    'AION_CHAT_AUTH_SECRET': secrets.token_hex(32),
    'AION_CREDENTIAL_ENCRYPTION_KEY': (
        os.environ.get('AION_CREDENTIAL_ENCRYPTION_KEY') or secrets.token_hex(32)
    ),
    'AION_API_KEY_BOOTSTRAP': f"aion_dev_{secrets.token_hex(16)}",
    'REDIS_PASSWORD': redis_password,

    # Auth
    'AION_CHAT_PASSWORD_AUTH': '1',
    'AION_ADMIN_PASSWORD_AUTH': '1',
    'AION_SETUP_ADMIN_BOOTSTRAP': '1',
    'AION_SETUP_ADMIN_DEFAULT_IDENTIFIER': 'admin',
    'AION_SETUP_ADMIN_DEFAULT_PASSWORD': 'admin'
}

domain = config['DOMAIN']
base_url = "http://localhost" if domain == ":80" or not domain else (domain if domain.startswith("http") else f"https://{domain}")
config['AION_PUBLIC_API_URL'] = f"{base_url}/api"
config['AION_CORS_ORIGINS'] = base_url
config['NEXT_PUBLIC_AION_API_URL'] = "/api"
config['NEXT_PUBLIC_AION_ADMIN_UI_URL'] = "/admin"

# Sandbox config
if os.path.exists(config['AION_PODMAN_SOCKET_HOST']):
    config['AION_SANDBOX_BACKEND'] = 'container'
    config['AION_CONTAINER_RUNTIME'] = 'podman'
else:
    config['AION_SANDBOX_BACKEND'] = 'subprocess'
    print(f"[warning] Podman socket not found at {config['AION_PODMAN_SOCKET_HOST']}. Defaulting to subprocess sandbox.")

# Quando AION_REUSE_DATA=1 o la chiave è già nel .env target, non sovrascrivere
# AION_CREDENTIAL_ENCRYPTION_KEY: cambiarla renderebbe illeggibile il DB esistente.
REUSE_DATA = os.environ.get('AION_REUSE_DATA', '0') == '1'
# Chiavi la cui sovrascrittura è protetta in modalità reuse
PROTECTED_IF_SET = {'AION_CREDENTIAL_ENCRYPTION_KEY'} if REUSE_DATA else set()

new_lines = []
existing_keys = []
for line in lines:
    replaced = False
    for k, v in config.items():
        if line.startswith(f"{k}="):
            existing_val = line.split('=', 1)[1].strip().rstrip('\n')
            if k in PROTECTED_IF_SET and existing_val:
                # Mantieni il valore già presente nel .env
                new_lines.append(line)
                print(f"[info] Manteno {k} esistente (AION_REUSE_DATA=1).")
            else:
                new_lines.append(f"{k}={v}\n")
            existing_keys.append(k)
            replaced = True
            break
    if not replaced:
        new_lines.append(line)
        if '=' in line and not line.startswith('#'):
            existing_keys.append(line.split('=')[0])

new_lines.append("\n# --- AION GHCR installer ---\n")
# Ensure any missing keys are added
for k, v in config.items():
    if k not in existing_keys:
        new_lines.append(f"{k}={v}\n")

with open(env_file, 'w') as f:
    f.writelines(new_lines)
EOF

chmod 644 .env
echo "[ok] .env generated."

# Fix ownership if run with sudo
if [ -n "${SUDO_USER:-}" ]; then
    chown -R "$SUDO_USER" "$AION_INSTALL_DIR"
fi

if [ -z "${AION_API_URL:-}" ] || [ -z "${AION_LLM_API_KEY:-}" ]; then
    echo ""
    echo "[action required] Configurazione LLM incompleta — il primo messaggio in chat fallirà."
    echo "  Modifica: $AION_INSTALL_DIR/.env"
    [ -z "${AION_API_URL:-}" ]      && echo "  • AION_API_URL     (es. http://ollama-host:11434/v1  oppure  https://api.openai.com/v1)"
    [ -z "${AION_LLM_API_KEY:-}" ]  && echo "  • AION_LLM_API_KEY (chiave API del provider)"
    [ -z "${AION_MODEL:-}" ]        && echo "  • AION_MODEL       (es. qwen3:8b  oppure  gpt-4o)"
    echo ""
    echo "  Dopo aver editato il .env, riavvia il backend:"
    echo "  docker compose -f docker-compose.ghcr.yml restart backend"
    echo ""
fi

# --- Step 4: Optimal Tuning ---
if [ "$AION_SKIP_TUNING" -eq 0 ]; then
    echo "--- Step 4: Applying Optimal Environment Tuning ---"
    if python3 scripts/apply_optimal_aion_env.py --env .env -y; then
        echo "[ok] Tuning applied successfully."
    else
        echo "[warning] Tuning script failed. This is non-fatal. Continuing..."
    fi
else
    echo "--- Step 4: Skipping Tuning ---"
fi

# --- Step 5 & 6: Startup & State ---
echo "--- Step 5: State & Summary ---"

INSTALL_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
cat > .aion-install.json <<EOF
{
  "version": "$AION_VERSION",
  "installed_at": "$INSTALL_DATE",
  "compose_file": "docker-compose.ghcr.yml",
  "install_dir": "$AION_INSTALL_DIR",
  "repo": "$AION_REPO"
}
EOF
echo "[ok] Wrote .aion-install.json"

if [ "$AION_SKIP_START" -eq 0 ]; then
    echo "--- Step 6: Starting Stack ---"
    docker compose -f docker-compose.ghcr.yml pull
    docker compose -f docker-compose.ghcr.yml up -d --no-build --remove-orphans
    
    echo "Waiting for backend to be healthy..."
    # Polling health
    for i in {1..36}; do
        HEALTH_STATUS=$(docker compose -f docker-compose.ghcr.yml ps --format json | grep -i '"Service":"backend"' | grep -io '"Health":"healthy"' || true)
        if [ -n "$HEALTH_STATUS" ]; then
            if curl -fsS "http://localhost:$CADDY_HTTP_PORT/api/health" >/dev/null 2>&1; then
                echo "[ok] Backend is healthy!"
                break
            fi
        fi
        sleep 5
        if [ "$i" -eq 36 ]; then
            echo "[warning] Timeout waiting for backend to become healthy."
        fi
    done
else
    echo "--- Step 6: Skipping Stack Startup ---"
fi

echo ""
echo "=== AION Agent Installation Complete ==="
echo "Install directory: $AION_INSTALL_DIR"
echo "Chat UI:           http://localhost:$CADDY_HTTP_PORT/"
echo "Admin UI:          http://localhost:$CADDY_HTTP_PORT/admin"
echo "API Docs:          http://localhost:$CADDY_HTTP_PORT/docs/"
echo "Bootstrap Admin:   admin / admin (must change on first login)"
echo ""
echo "Useful commands:"
echo "  cd $AION_INSTALL_DIR"
echo "  docker compose -f docker-compose.ghcr.yml logs -f"
echo "  docker compose -f docker-compose.ghcr.yml ps"
echo "  docker compose -f docker-compose.ghcr.yml down"
echo "========================================"

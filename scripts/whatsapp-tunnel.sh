#!/usr/bin/env bash
# Tunnel Cloudflare temporaneo + stack Docker, per collegare WhatsApp senza un dominio.
#
# 1. apre un quick tunnel (https://<random>.trycloudflare.com) verso Caddy sulla porta HTTP locale;
# 2. genera un override compose che punta gli URL pubblici del backend al tunnel
#    (AION_PUBLIC_API_URL, AION_OAUTH_REDIRECT_BASE_URL, AION_PUBLIC_CHAT_URL,
#    AION_CHAT_URL) senza toccare .env;
# 3. esegue `docker compose up -d --build`;
# 4. stampa URL di callback per Meta e resta in primo piano: Ctrl+C chiude il tunnel.
#
# L'URL del tunnel cambia a ogni avvio: va reinserito su Meta (Webhook → Callback URL).
# Uso: scripts/whatsapp-tunnel.sh [--no-build] [--port N] [--down-on-exit]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$ROOT/.aion-tunnel"
LOG_FILE="$STATE_DIR/cloudflared.log"
OVERRIDE_FILE="$STATE_DIR/docker-compose.tunnel.yml"

BUILD=1
DOWN_ON_EXIT=0
PORT=""

usage() {
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Opzioni:
  --no-build      docker compose up -d senza --build
  --port N        porta HTTP locale di Caddy (default: CADDY_HTTP_PORT da .env, altrimenti 80)
  --down-on-exit  all'uscita esegue anche docker compose down
  -h, --help      questo messaggio
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build) BUILD=0 ;;
    --down-on-exit) DOWN_ON_EXIT=1 ;;
    --port)
      PORT="${2:-}"
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Opzione sconosciuta: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

die() {
  echo "ERRORE: $*" >&2
  exit 1
}

command -v cloudflared >/dev/null || die "cloudflared non trovato. macOS: brew install cloudflared"
command -v docker >/dev/null || die "docker non trovato"
docker info >/dev/null 2>&1 || die "il demone Docker non risponde (Docker Desktop è avviato?)"
[[ -f "$ROOT/.env" ]] || die "manca $ROOT/.env (cp .env.docker.example .env oppure cp .env.example .env)"

# Legge una chiave dal .env senza eseguirlo (niente `source`: i valori possono contenere di tutto).
env_value() {
  grep -E "^[[:space:]]*$1=" "$ROOT/.env" | tail -n 1 | cut -d= -f2- | sed -e 's/[[:space:]]*#.*$//' -e 's/^["'\'']//' -e 's/["'\'']$//'
}

if [[ -z "$PORT" ]]; then
  PORT="$(env_value CADDY_HTTP_PORT || true)"
  PORT="${PORT:-80}"
fi
[[ "$PORT" =~ ^[0-9]+$ ]] || die "porta non valida: $PORT"

domain="$(env_value DOMAIN || true)"
if [[ -n "$domain" && "$domain" != :* ]]; then
  echo "ATTENZIONE: DOMAIN=$domain nel .env. Caddy risponde solo a quell'host e il tunnel riceverà 404." >&2
  echo "            Per il tunnel usa DOMAIN=:80 (modalità HTTP locale)." >&2
fi

mkdir -p "$STATE_DIR"
: >"$LOG_FILE"

compose_files=(-f "$ROOT/docker-compose.yml")
# `-f` disattiva il caricamento automatico dell'override locale: lo includiamo noi.
[[ -f "$ROOT/docker-compose.override.yml" ]] && compose_files+=(-f "$ROOT/docker-compose.override.yml")

CF_PID=""
STACK_UP=0
cleanup() {
  trap - EXIT INT TERM
  echo
  if [[ -n "$CF_PID" ]] && kill -0 "$CF_PID" 2>/dev/null; then
    echo "Chiudo il tunnel (pid $CF_PID)…"
    kill "$CF_PID" 2>/dev/null || true
    wait "$CF_PID" 2>/dev/null || true
  fi
  if [[ "$DOWN_ON_EXIT" == 1 ]]; then
    echo "docker compose down…"
    docker compose "${compose_files[@]}" -f "$OVERRIDE_FILE" down || true
  elif [[ "$STACK_UP" == 1 ]]; then
    echo "Lo stack resta avviato con gli URL del tunnel ormai chiuso."
    echo "Per tornare agli URL del .env: docker compose up -d backend"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

echo "Avvio il tunnel Cloudflare verso http://localhost:$PORT …"
cloudflared tunnel --no-autoupdate --url "http://localhost:$PORT" >"$LOG_FILE" 2>&1 &
CF_PID=$!

TUNNEL_URL=""
for _ in $(seq 1 60); do
  kill -0 "$CF_PID" 2>/dev/null || die "cloudflared si è chiuso. Log: $LOG_FILE"$'\n'"$(tail -n 20 "$LOG_FILE")"
  TUNNEL_URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_FILE" | head -n 1 || true)"
  [[ -n "$TUNNEL_URL" ]] && break
  sleep 1
done
[[ -n "$TUNNEL_URL" ]] || die "nessun URL dal tunnel dopo 60s. Log: $LOG_FILE"
echo "Tunnel: $TUNNEL_URL"

cat >"$OVERRIDE_FILE" <<EOF
# Generato da scripts/whatsapp-tunnel.sh: non modificare, viene riscritto a ogni avvio.
services:
  backend:
    environment:
      AION_PUBLIC_API_URL: "$TUNNEL_URL/api"
      # Va sovrascritto anche questo: _public_api_base_url() (usato per il webhook URL
      # mostrato in admin-ui) lo legge PRIMA di AION_PUBLIC_API_URL, e il compose lo
      # deriva dal .env (es. http://localhost:8001) se non è impostato esplicitamente.
      AION_OAUTH_REDIRECT_BASE_URL: "$TUNNEL_URL/api"
      AION_PUBLIC_CHAT_URL: "$TUNNEL_URL"
      AION_CHAT_URL: "$TUNNEL_URL"
EOF

up_args=(up -d)
[[ "$BUILD" == 1 ]] && up_args+=(--build)
echo "docker compose ${up_args[*]} …"
(cd "$ROOT" && docker compose "${compose_files[@]}" -f "$OVERRIDE_FILE" "${up_args[@]}")
STACK_UP=1

# Il DNS del sottodominio trycloudflare può impiegare qualche secondo a propagarsi.
echo "Attendo che il backend risponda attraverso il tunnel…"
healthy=0
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null --max-time 5 "$TUNNEL_URL/api/health"; then
    healthy=1
    break
  fi
  sleep 3
done

cat <<EOF

────────────────────────────────────────────────────────────────────
 Callback URL per Meta (App → WhatsApp → Configurazione → Webhook):

   $TUNNEL_URL/api/v1/channels/whatsapp/webhook

 Verify token: admin-ui → WhatsApp (http://localhost:$PORT/admin/whatsapp)
 Poi su Meta: "Verifica e salva" e sottoscrivi il campo "messages".

 Chat-ui pubblica: $TUNNEL_URL
 Log del tunnel:   $LOG_FILE
────────────────────────────────────────────────────────────────────
EOF
if [[ "$healthy" == 0 ]]; then
  echo "ATTENZIONE: $TUNNEL_URL/api/health non risponde ancora. Controlla: docker compose ps / logs backend caddy" >&2
fi
echo "Tunnel attivo. Ctrl+C per chiuderlo."

wait "$CF_PID" || true
echo "cloudflared terminato. Log: $LOG_FILE"

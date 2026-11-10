#!/usr/bin/env bash
# test-self-update.sh — end-to-end test of the one-click upgrade (aion-updater sidecar).
#
# Purpose: verify on a developer machine (Docker Desktop / Linux, no Podman)
# that the sidecar applies a real hop chain in "hybrid" mode:
#   <old release> → … → <latest release> (GHCR pulls) → local (build from this clone)
#
# What it does:
#   1. installs an old GHCR release in a throwaway directory with THIS clone's
#      install.sh (`--version <from> --no-podman`);
#   2. enables hybrid mode in that .env (AION_UPGRADE_FINAL_LOCAL=1,
#      AION_LOCAL_REPO_DIR=<this clone>);
#   3. creates an UNCOMMITTED test upgrade script in the clone
#      (scripts/upgrades/99.99.99.py) that writes a marker in .env — it proves
#      that `upgrade_runner.py --to local` runs unreleased scripts; it is removed
#      on exit;
#   4. bootstrap: until a published release contains the updater, the old
#      compose file has no `updater` service, so the sidecar is built from the
#      clone (`aion-updater:local`) and started through a generated override
#      (docker-compose.updater-dev.yml, which `extends` the clone's service);
#   5. starts the upgrade with POST /upgrade directly on the sidecar (the old
#      admin-ui has no button) and follows data/updater/status.json;
#   6. checks the outcome (AION_VERSION=local, marker, healthy services, updater
#      recreated on the :local image).
#
# With --fail-first the test upgrade script raises on the first run: the run
# must end "failed"; the script then removes the failure trigger and retries,
# which must resume from the local hop only.
#
# Once a release that ships the updater exists, prefer starting from it and
# pressing "Update now" in http://localhost/admin (step 4 is then unnecessary).
# Docs: docs/deployment/self-update.md
#
# Usage:
#   scripts/dev/test-self-update.sh --from 1.6.0 [--dir <path>] [--fail-first] [--cleanup]

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FROM=""
# Default under $HOME: Docker Desktop shares it with the VM (bind mounts work).
DIR="${HOME}/.aion-selfupdate-test"
FAIL_FIRST=0
CLEANUP=0
TIMEOUT_SEC=3600
TEST_SCRIPT="$REPO/scripts/upgrades/99.99.99.py"
UPDATER_IMAGE="ghcr.io/aion-by-asa-computer/aion-updater:local"

usage() {
    sed -n '2,37p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --from) FROM="$2"; shift 2 ;;
        --dir) DIR="$2"; shift 2 ;;
        --fail-first) FAIL_FIRST=1; shift ;;
        --cleanup) CLEANUP=1; shift ;;
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1"; usage 1 ;;
    esac
done
[ -n "$FROM" ] || { echo "[error] --from <old release> is required (e.g. --from 1.6.0)"; exit 1; }

log() { printf '\n=== %s ===\n' "$*"; }
fail() { echo "[FAIL] $*"; exit 1; }

# Read a key from the install's .env (last occurrence wins, like compose).
env_get() { grep -E "^$1=" "$DIR/.env" 2>/dev/null | tail -n1 | cut -d= -f2- || true; }

# Set/replace a key in the install's .env.
env_set() {
    python3 - "$DIR/.env" "$1" "$2" <<'PY'
import sys
from pathlib import Path
path, key, value = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = [l for l in path.read_text().splitlines() if not l.startswith(key + "=")]
lines.append(f"{key}={value}")
path.write_text("\n".join(lines) + "\n")
PY
}

compose() { (cd "$DIR" && docker compose -f docker-compose.ghcr.yml "$@"); }

# Always remove the uncommitted test upgrade script from the clone.
cleanup() {
    rm -f "$TEST_SCRIPT"
    if [ "$CLEANUP" = "1" ] && [ -f "$DIR/docker-compose.ghcr.yml" ]; then
        echo "[info] Tearing down the test stack in $DIR"
        compose -f docker-compose.updater-dev.yml down -v --remove-orphans >/dev/null 2>&1 || true
        rm -rf "$DIR"
    fi
}
trap cleanup EXIT

# POST /upgrade (or GET <path>) on the sidecar from inside its container: the
# sidecar publishes no port, by design.
updater_call() {
    local method="$1" path="$2"
    (cd "$DIR" && docker compose -f docker-compose.ghcr.yml -f docker-compose.updater-dev.yml \
        exec -T updater python3 - "$method" "$path" <<'PY'
import json, os, sys, urllib.request, urllib.error
method, path = sys.argv[1], sys.argv[2]
body = json.dumps({"requested_by": "test-self-update.sh"}).encode() if method == "POST" else None
req = urllib.request.Request(f"http://127.0.0.1:8090{path}", data=body, method=method,
    headers={"Authorization": "Bearer " + os.environ["AION_UPDATER_TOKEN"], "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=180) as r:
        print(r.status, r.read().decode())
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode())
PY
    )
}

# Follow status.json until the run ends; prints phase changes. Echoes the final state.
wait_for_run() {
    local status="$DIR/data/updater/status.json" last="" start now line
    start=$(date +%s)
    while :; do
        if [ -f "$status" ]; then
            line=$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print(s.get("state",""), s.get("hop_to") or "-", s.get("phase",""))' "$status" 2>/dev/null || true)
            if [ -n "$line" ] && [ "$line" != "$last" ]; then
                echo "  [$(date +%H:%M:%S)] state/hop/phase: $line" >&2
                last="$line"
            fi
            case "$line" in
                succeeded*) echo succeeded; return 0 ;;
                failed*) echo failed; return 0 ;;
            esac
        fi
        now=$(date +%s)
        [ $((now - start)) -lt "$TIMEOUT_SEC" ] || { echo timeout; return 0; }
        sleep 5
    done
}

# ---------------------------------------------------------------------------
log "1. Fresh install of release $FROM in $DIR"
if [ -e "$DIR" ]; then
    fail "$DIR already exists: remove it (or pass --dir) to start from a clean install"
fi
mkdir -p "$DIR"
(cd "$DIR" && bash "$REPO/scripts/install.sh" --version "$FROM" --dir "$DIR" \
    --no-podman --no-tuning --force </dev/null)
[ "$(env_get AION_VERSION)" = "$FROM" ] || fail "AION_VERSION is not $FROM after install"
[ -n "$(env_get AION_UPDATER_TOKEN)" ] || fail "install.sh did not write AION_UPDATER_TOKEN"

log "2. Hybrid mode: final hop built from $REPO"
env_set AION_UPGRADE_FINAL_LOCAL 1
env_set AION_LOCAL_REPO_DIR "$REPO"

log "3. Unreleased test upgrade script ($TEST_SCRIPT)"
[ -e "$TEST_SCRIPT" ] && fail "$TEST_SCRIPT already exists in the clone"
cat >"$TEST_SCRIPT" <<'PY'
"""TEST ONLY (created by scripts/dev/test-self-update.sh, never commit).

Proves that `upgrade_runner.py --to local` runs unreleased upgrade scripts:
writes a marker in .env; raises while the failure trigger file exists.
"""
from pathlib import Path


def upgrade(ctx) -> None:
    if Path("/app/data/.selfupdate-test-fail").exists():
        raise RuntimeError("self-update test: simulated upgrade script failure")
    ctx.ensure_env_key("AION_SELFUPDATE_TEST_MARKER", "1")
PY
if [ "$FAIL_FIRST" = "1" ]; then
    touch "$DIR/data/.selfupdate-test-fail"
fi

log "4. Bootstrap: build $UPDATER_IMAGE from the clone and start it"
docker build -f "$REPO/docker/Dockerfile.updater" -t "$UPDATER_IMAGE" "$REPO"
cat >"$DIR/docker-compose.updater-dev.yml" <<EOF
# Generated by scripts/dev/test-self-update.sh — bootstrap only: the installed
# release's compose file has no updater service yet, so it is taken from the clone.
services:
  updater:
    extends:
      file: $REPO/docker-compose.ghcr.yml
      service: updater
    image: $UPDATER_IMAGE
    environment:
      AION_UPDATER_SELF_IMAGE: $UPDATER_IMAGE
EOF
(cd "$DIR" && docker compose -f docker-compose.ghcr.yml -f docker-compose.updater-dev.yml up -d updater)
for _ in $(seq 1 30); do
    updater_call GET /healthz 2>/dev/null | grep -q '^200' && break
    sleep 2
done
echo "[info] Plan:"
updater_call GET "/plan?refresh=1"

log "5. Start the upgrade (POST /upgrade)"
resp=$(updater_call POST /upgrade)
echo "$resp"
[[ "$resp" == 202* ]] || fail "POST /upgrade did not return 202"
result=$(wait_for_run)

if [ "$FAIL_FIRST" = "1" ]; then
    [ "$result" = "failed" ] || fail "expected a failed run with --fail-first, got: $result"
    echo "[ok] First run failed as expected; AION_VERSION=$(env_get AION_VERSION)"
    [ "$(env_get AION_VERSION)" != "$FROM" ] || echo "[warn] no GHCR hop was applied before the failure"
    rm -f "$DIR/data/.selfupdate-test-fail"
    log "5b. Retry: must resume from the local hop only"
    # The sidecar was not recreated (failed run): it still answers on the bootstrap container.
    plan=$(updater_call GET "/plan?refresh=1")
    echo "$plan"
    echo "$plan" | grep -q '"chain": \["local"\]' || fail "retry plan should contain only the local hop"
    resp=$(updater_call POST /upgrade)
    [[ "$resp" == 202* ]] || fail "retry POST /upgrade did not return 202: $resp"
    result=$(wait_for_run)
fi

[ "$result" = "succeeded" ] || {
    echo "[info] Last log lines:"
    tail -n 40 "$(ls -t "$DIR"/data/updater/logs/*.log | head -n1)" || true
    fail "upgrade ended with: $result"
}

log "6. Checks"
[ "$(env_get AION_VERSION)" = "local" ] || fail "AION_VERSION is $(env_get AION_VERSION), expected local"
echo "[ok] AION_VERSION=local"
[ "$(env_get AION_SELFUPDATE_TEST_MARKER)" = "1" ] || fail "test marker missing: unreleased upgrade script not run"
echo "[ok] unreleased upgrade script executed (marker present)"
LOG=$(ls -t "$DIR"/data/updater/logs/*.log | head -n1)
grep -q "Copio file infrastrutturali dal clone" "$LOG" || fail "local hop not found in $LOG"
echo "[ok] local hop in $LOG"

# The finalize helper recreates the updater ~5s after success, then backend health settles.
sleep 20
compose ps
unhealthy=$(compose ps --format json | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
rows = json.loads(raw) if raw.startswith("[") else [json.loads(l) for l in raw.splitlines() if l]
print(" ".join(r["Service"] for r in rows if r.get("Health") not in ("", "healthy") or r.get("State") != "running"))')
[ -z "$unhealthy" ] || fail "services not running/healthy: $unhealthy"
echo "[ok] all services running/healthy"
img=$(compose ps --format '{{.Service}} {{.Image}}' | awk '$1=="updater"{print $2}')
[ "$img" = "$UPDATER_IMAGE" ] || fail "updater runs on '$img', expected $UPDATER_IMAGE"
echo "[ok] updater recreated on $img"

echo ""
echo "[PASS] Self-update end-to-end test succeeded (install dir: $DIR)."
[ "$CLEANUP" = "1" ] || echo "       Inspect it, then: (cd $DIR && docker compose -f docker-compose.ghcr.yml down -v) && rm -rf $DIR"

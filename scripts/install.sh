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

# --- Usage & Flags Parsing ---
usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --dir <path>       Install directory (default: \$PWD/aion-agent)
  --version <tag>    AION version to install (default: latest)
  --domain <domain>  Domain for Let's Encrypt (default: :80 for local HTTP)
  --email <email>    Email for Let's Encrypt
  --no-tuning        Skip optimal environment tuning
  --no-start         Do not start the stack after installation
  --force            Overwrite existing .env if present
  --local            Use local repository files instead of downloading from GitHub (for testing)
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

# --- Error Handling ---
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
    'AION_CHAT_AUTH_SECRET': secrets.token_hex(32),
    'AION_CREDENTIAL_ENCRYPTION_KEY': secrets.token_hex(32),
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

new_lines = []
existing_keys = []
for line in lines:
    replaced = False
    for k, v in config.items():
        if line.startswith(f"{k}="):
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
    echo "[warning] LLM configuration (AION_API_URL, AION_LLM_API_KEY) not provided. Please edit .env later."
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

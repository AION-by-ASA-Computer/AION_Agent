---
title: Filesystem policy and PNG promo export
sidebar_position: 2
description: Template fs_policy, exec in sandbox, Playwright for MCP promo_render and integration in setup/upgrade scripts.
---

# Filesystem policy and PNG promo export

Two optional features share the same setup hook: **YAML policy for filesystem/exec** and **Playwright for the `promo_render` MCP server**.

## What the scripts do

| Script | Role |
|--------|--------|
| [`scripts/runtime_extras_setup.py`](../../scripts/runtime_extras_setup.py) | Copies `fs_policy` template to `config/`, appends promo keys to `.env`, optional dev policy activation, automatic patch of `wren` allowlist, installs Playwright |
| [`scripts/setup_promo_playwright.sh`](../../scripts/setup_promo_playwright.sh) | `pip install playwright` + `playwright install chromium` on the backend Python (`.venv` or `mcp_servers/promo_render/.venv`) |
| [`scripts/setup-aion-env.sh`](../../scripts/setup-aion-env.sh) | Env wizard + `--prepare-runtime` → invokes `setup_core` → runtime extras |
| [`scripts/upgrade-aion.sh`](../../scripts/upgrade-aion.sh) | Local upgrade or `--docker` → `upgrade_core` → runtime extras after `sync_config` / `sync_mcp_servers` |

### Useful commands

```bash
# Initial setup (venv + sync + Playwright promo, if not skipped)
./scripts/setup-aion-env.sh

# Only runtime extras (dry-run)
python3 scripts/runtime_extras_setup.py --dry-run

# Enable sandbox exec (local dev only)
./scripts/setup-aion-env.sh --enable-fs-policy-dev
# or
./scripts/upgrade-aion.sh --enable-fs-policy-dev

# Skip Chromium download (~150 MB)
./scripts/upgrade-aion.sh --skip-promo-playwright
```

After changes to `AION_FS_POLICY_PATH` or Playwright installation: **restart the backend** (`./scripts/dev-api.sh` or `backend` container).

---

## Filesystem policy (`AION_FS_POLICY_PATH`)

### Default

If `AION_FS_POLICY_PATH` is empty, the runtime uses the **in-code** policy (`src/runtime/agent_fs_policy.py`): generally **`exec.enabled=false`**. The `sandbox_exec_allowlisted` tool remains disabled until you point to a YAML with `exec.enabled: true`.

### Templates in `config_std/`

| File | Usage |
|------|-----|
| `fs_policy.example.yaml` | Commented example for production |
| `fs_policy.dev.yaml` | Dev: `exec.enabled: true` with minimal allowlist (`grep`, `wc`, `sort`) |

`runtime_extras_setup` copies templates to `config/` if missing (idempotent).

### Dev activation (`--enable-fs-policy-dev`)

1. Copies `config/fs_policy.dev.yaml` → `config/fs_policy.yaml`
2. Adds to `.env`: `AION_FS_POLICY_PATH=config/fs_policy.yaml` (only if the key does not exist)

**Mandatory:** without `AION_FS_POLICY_PATH` in `.env`, the backend ignores `config/fs_policy.yaml` and remains `exec.enabled=false` (error `exec_disabled`).

For production: start from `fs_policy.example.yaml`, adapt allowlist and paths, **do not** use the dev file without security review.

### Dev allowlist (`fs_policy.dev.yaml`)

| Category | Executables |
|-----------|------------|
| Python office/docx | `python`, `python3` — only scripts under `scripts/`, `workspace/`, `uploads/`, `derived/` (no `-c` / `-m`) |
| Semantic SQL | `wren` — necessary for Postgres queries and MDL integration |
| Text | `grep`, `wc`, `sort`, `head`, `tail`, `cat`, `cut`, `tr`, `uniq`, `file` |
| File system | `find`, `ls`, `du`, `cp`, `mv`, `mkdir`, `touch`, `zip`, `unzip` |
| Documents | `pandoc`, `pdftoppm` |

**Not included (by design):** `bash`, `sh`, `curl`, `wget`, `pip`, `npm` (use `sandbox_install_*` / `sandbox_run_*_file`).

### Promo PNG and exec

PNG export **does not** use `sandbox_exec`: it uses Playwright in the `promo_render` MCP process. The exec policy is used for other workflows (grep on workspace, allowlisted Python scripts under `scripts/` after `skill_view` — see [Skill and system prompt](./skills-and-prompts.md)).

---

## Promo render MCP (Playwright)

See also [Promo Render MCP](../mcp/promo-render.md).

### Variables

| Variable | Typical default | Description |
|-----------|----------------|-------------|
| `AION_PROMO_CAPTURE_ENABLED` | `1` | `0` disables capture |
| `AION_PROMO_CAPTURE_TIMEOUT_MS` | (optional) | Capture timeout |

Automatic append from setup/upgrade if absent in `.env`.

### Correct Python

Playwright must be installed on the **same interpreter** that starts the backend/MCP, not on the chat session venv. `setup_promo_playwright.sh` tries in order:

1. `.venv/bin/python`
2. `mcp_servers/promo_render/.venv/bin/python`
3. `system python3`

Verify in chat (**Graphic Designer** profile): tool `promo_check_environment` → `"ok": true`.

---

## Docker Compose

- `./scripts/setup-aion-env.sh --docker` only copies `.env.docker.example`; it **does not** create a local venv nor install Playwright on the host.
- `./scripts/upgrade-aion.sh --docker` still runs `runtime_extras_setup` on the host (`config/` templates, `.env` keys), but **Chromium must be installed in the backend image** if promo in container is needed.

One-off example in the backend container (after `docker compose up`):

```bash
docker compose exec backend bash -c \
  'python -m pip install "playwright>=1.49.0" && python -m playwright install --with-deps chromium'
```

For persistent production, extend `docker/Dockerfile.backend` with the same commands in the runtime stage (including the installation of system dependencies).

---

## Code references

- Policy loader: `src/runtime/agent_fs_policy.py`
- Capture: `src/tools/promo_capture.py`
- MCP: `mcp_servers_std/promo_render/`
- Recommended profile: `config_std/profiles/graphic_designer.yaml`

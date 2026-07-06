#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"
REQ = ROOT / "requirements.txt"
ENSURE_SKILL_PACKAGES = ROOT / "scripts" / "ensure_skill_packages.py"


def _read_version() -> str:
    """Legge la versione dal file centralizzato version.json nella root del repo."""
    try:
        version_file = ROOT / "version.json"
        return json.loads(version_file.read_text(encoding="utf-8")).get(
            "version", "unknown"
        )
    except Exception:
        return "unknown"


@dataclass
class Report:
    ok: list[str] = field(default_factory=list)
    warn: list[str] = field(default_factory=list)
    fail: list[str] = field(default_factory=list)

    def log_ok(self, msg: str) -> None:
        print(f"[OK] {msg}")
        self.ok.append(msg)

    def log_warn(self, msg: str) -> None:
        print(f"[WARN] {msg}")
        self.warn.append(msg)

    def log_fail(self, msg: str) -> None:
        print(f"[FAIL] {msg}")
        self.fail.append(msg)


def _prune_junk_profile_files(*, dry_run: bool, report: Report) -> None:
    """Remove duplicate/legacy YAML files from config/profiles/ (Finder 'copy', *_OLD)."""
    profiles_dir = ROOT / "config" / "profiles"
    if not profiles_dir.is_dir():
        return
    for path in sorted(profiles_dir.glob("*.yaml")):
        stem = path.stem.lower()
        if not (stem.endswith("_old") or " copy" in stem):
            continue
        if dry_run:
            report.log_warn(f"Would remove junk profile file: {path.name}")
            continue
        try:
            path.unlink()
            report.log_ok(f"Removed junk profile file: {path.name}")
        except OSError as exc:
            report.log_warn(f"Could not remove {path.name}: {exc}")
    for path in sorted(profiles_dir.iterdir()):
        if not path.is_dir():
            continue
        name = path.name.lower()
        if " copy" not in name and not name.endswith("_old"):
            continue
        if dry_run:
            report.log_warn(f"Would remove junk profile directory: {path.name}")
            continue
        try:
            import shutil

            shutil.rmtree(path)
            report.log_ok(f"Removed junk profile directory: {path.name}")
        except OSError as exc:
            report.log_warn(f"Could not remove directory {path.name}: {exc}")


def _ensure_skill_packages(
    py_exec: str, dry_run: bool, report: Report, *, force_mcp: bool
) -> None:
    if not ENSURE_SKILL_PACKAGES.is_file():
        report.log_warn("ensure_skill_packages.py missing — skip skill sync")
        return
    rc = _run(
        [py_exec, str(ENSURE_SKILL_PACKAGES)]
        + (["--dry-run"] if dry_run else [])
        + (["--force-mcp-sync"] if force_mcp else []),
        dry_run=dry_run,
    )
    if rc != 0:
        report.log_warn("ensure_skill_packages exited non-zero")
    else:
        report.log_ok("Skill packages (config_std + config + MCP sync)")


def _run(
    cmd: list[str],
    dry_run: bool = False,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> int:
    if dry_run:
        print(f"[dry-run] {' '.join(cmd)}")
        return 0
    kwargs: dict = {"cwd": str(cwd or ROOT)}
    if env is not None:
        kwargs["env"] = env
    return subprocess.run(cmd, **kwargs).returncode


def _docker_client_env(env_file: Path | None) -> dict[str, str]:
    """Env per `docker compose` (BuildKit + override da .env se presente)."""
    out = os.environ.copy()
    out.setdefault("DOCKER_BUILDKIT", "1")
    if env_file and env_file.is_file():
        for k, v, _ in _parse_env_simple(env_file):
            if k == "DOCKER_BUILDKIT" and v.strip():
                out["DOCKER_BUILDKIT"] = v.strip()
    return out


# Mapping autoritativo legacy → new (deve combaciare con scripts.setup_aion_env.LEGACY_RENAME).
# Tenuto duplicato qui per evitare di importare setup_aion_env (che ha dipendenze pesanti).
_ENV_LEGACY_RENAME: dict[str, str] = {
    "AION_CHAINLIT_PASSWORD_AUTH": "AION_CHAT_PASSWORD_AUTH",
    "CHAINLIT_AUTH_SECRET": "AION_CHAT_AUTH_SECRET",
    "AION_SETUP_CHAINLIT_IDENTIFIER": "AION_SETUP_CHAT_IDENTIFIER",
    "AION_SETUP_CHAINLIT_PASSWORD": "AION_SETUP_CHAT_PASSWORD",
}


def _parse_env_simple(path: Path) -> "list[tuple[str, str, str]]":
    """Parser minimale: ritorna lista di (key, value, original_line)
    preservando l'ordine e i commenti.
    Per righe non-KEY=VAL ritorna ('', '', original_line).
    """
    out: list[tuple[str, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return out
    for raw in text.splitlines():
        s = raw.lstrip()
        if not s or s.startswith("#"):
            out.append(("", "", raw))
            continue
        if "=" not in raw:
            out.append(("", "", raw))
            continue
        key, _, val = raw.partition("=")
        out.append((key.strip(), val.strip(), raw))
    return out


def _rewrite_env_key(env_path: Path, key: str, value: str) -> bool:
    """Replace KEY=... with KEY=value (first occurrence); append if missing."""
    if not env_path.is_file():
        return False
    entries = _parse_env_simple(env_path)
    out_lines: list[str] = []
    seen: set[str] = set()
    found = False
    for k, _, raw in entries:
        if not k:
            out_lines.append(raw)
            continue
        if k in seen:
            continue
        seen.add(k)
        if k == key:
            out_lines.append(f"{key}={value}")
            found = True
        else:
            out_lines.append(raw)
    if not found:
        out_lines.append(f"{key}={value}")
    try:
        env_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _migrate_env_legacy_keys(env_path: Path, *, dry_run: bool, report: Report) -> int:
    """Migra le chiavi legacy del .env ai nomi moderni (AION_CHAT_*).

    Comportamento:
      - Se il .env non esiste: noop (no error).
      - Per ogni OLD presente:
          * se NEW NON e' presente: rinomina OLD → NEW preservando il valore
          * se NEW e' presente: mantiene NEW e rimuove OLD (conflitto, NEW vince)
      - Backup .env.bak.YYYYMMDDHHMMSS prima di scrivere.
      - In dry-run: stampa solo cosa farebbe.
    Ritorna 0 in caso di successo, code non-zero se errore I/O.
    """
    if not env_path.is_file():
        report.log_ok("Migrate legacy env keys: .env non presente, skip")
        return 0

    entries = _parse_env_simple(env_path)
    # Mappa key → valore (ultimo wins se duplicato, comune in .env)
    values_present: dict[str, str] = {}
    for k, v, _ in entries:
        if k:
            values_present[k] = v
    found_legacy = [k for k in _ENV_LEGACY_RENAME if k in values_present]
    if not found_legacy:
        report.log_ok("Migrate legacy env keys: nessuna chiave legacy nel .env")
        return 0

    actions: list[str] = []
    new_entries: list[tuple[str, str, str]] = []
    handled: set[str] = set()  # evita di toccare OLD piu' di una volta
    # promote_value[NEW_KEY] = valore da scrivere quando incontriamo la prima
    # occorrenza di NEW (o di OLD da rinominare se NEW non esiste)
    promote_value: dict[str, str] = {}

    # Pre-calcolo: per ogni coppia (OLD, NEW), decidi quale valore vince
    for old_k, new_k in _ENV_LEGACY_RENAME.items():
        if old_k not in values_present:
            continue
        old_val = values_present[old_k]
        new_val = values_present.get(new_k, None)
        if new_val is None:
            # NEW assente → riconverti la riga OLD nella forma NEW (valore di OLD)
            promote_value[new_k] = old_val
            actions.append(f"RENAME {old_k} → {new_k} (valore preservato)")
        else:
            # Entrambe presenti: vince quella valorizzata (NEW di default se entrambe vuote o entrambe piene)
            if new_val == "" and old_val != "":
                promote_value[new_k] = old_val
                actions.append(
                    f"MERGE  {new_k} era vuoto → copio valore da {old_k}, dropy {old_k}"
                )
            else:
                promote_value[new_k] = new_val
                actions.append(f"DROP   {old_k} (entrambe presenti, {new_k} vince)")

    # Costruisce nuove entries:
    # - Le linee OLD vengono rimosse
    # - Le linee NEW (se presenti) vengono RISCRITTE col valore promosso
    # - Se NEW non era presente, sostituiamo la riga OLD con la riga NEW promossa
    new_emitted: set[str] = set()
    for k, v, raw in entries:
        if k in _ENV_LEGACY_RENAME:
            new_k = _ENV_LEGACY_RENAME[k]
            if k in handled:
                continue  # gia' processata: skip duplicato
            handled.add(k)
            if new_k in values_present:
                # NEW esisteva nel file: la sua riga la riscriveremo quando la incontriamo
                continue
            # NEW non c'era: emetto qui la riga NEW al posto della OLD
            if new_k not in new_emitted:
                val = promote_value.get(new_k, v)
                new_entries.append((new_k, val, f"{new_k}={val}"))
                new_emitted.add(new_k)
            continue
        if k in promote_value and k not in new_emitted:
            val = promote_value[k]
            new_entries.append((k, val, f"{k}={val}"))
            new_emitted.add(k)
            continue
        new_entries.append((k, v, raw))

    print("\n--- Migrazione chiavi legacy ---")
    for line in actions:
        print(f"  {line}")

    if dry_run:
        report.log_ok(
            f"Migrate legacy env keys: {len(actions)} azioni (dry-run, nessuna scrittura)"
        )
        return 0

    # Backup
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bak = env_path.with_suffix(env_path.suffix + f".bak.{ts}")
    try:
        bak.write_bytes(env_path.read_bytes())
    except Exception as e:
        report.log_fail(f"Backup .env fallito: {e}")
        return 3

    try:
        with env_path.open("w", encoding="utf-8", newline="\n") as f:
            for _, _, raw in new_entries:
                f.write(raw + "\n")
    except Exception as e:
        report.log_fail(f"Scrittura .env fallita: {e}")
        # Rollback dal backup
        try:
            env_path.write_bytes(bak.read_bytes())
        except Exception:
            pass
        return 4

    report.log_ok(
        f"Migrate legacy env keys: {len(actions)} azioni applicate (backup: {bak.name})"
    )
    return 0


_HOST_DATA_PATH_REWRITES: dict[str, str] = {
    "AION_DATA_DIR": "data",
    "AION_STORAGE_LOCAL_ROOT": "data",
    "AION_PROFILING_JSONL_DIR": "data/profiling",
    "AION_MCP_REGISTRY_LOCAL_PATH": "data/mcp_registry.local.yaml",
}


def _rewrite_docker_data_path(value: str, *, host_default: str) -> str | None:
    v = (value or "").strip()
    if not v.startswith("/app/data"):
        return None
    suffix = v[len("/app/data") :].lstrip("/")
    if not suffix:
        return host_default
    if host_default.endswith((".yaml", ".json", ".yml")):
        return host_default
    return f"data/{suffix}" if suffix else host_default


def _migrate_docker_data_paths_in_env(
    env_path: Path, *, dry_run: bool, report: Report
) -> int:
    """Rewrite /app/data/* paths in .env when upgrade runs outside Docker."""
    if Path("/.dockerenv").exists():
        report.log_ok("Migrate Docker data paths: inside container, skip")
        return 0
    if not env_path.is_file():
        report.log_ok("Migrate Docker data paths: .env non presente, skip")
        return 0

    entries = _parse_env_simple(env_path)
    values: dict[str, str] = {}
    for k, v, _ in entries:
        if k:
            values[k] = v

    actions: list[str] = []
    for key, host_default in _HOST_DATA_PATH_REWRITES.items():
        cur = values.get(key)
        if cur is None:
            continue
        new_val = _rewrite_docker_data_path(cur, host_default=host_default)
        if new_val and new_val != cur:
            actions.append(f"{key}: {cur!r} -> {new_val!r}")
            values[key] = new_val

    if not actions:
        report.log_ok("Migrate Docker data paths: nessun path /app/data nel .env")
        return 0

    if dry_run:
        for a in actions:
            print(f"  [dry-run] would rewrite {a}")
        report.log_ok(f"Migrate Docker data paths (dry-run): {len(actions)} rewrite(s)")
        return 0

    import shutil
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bak = env_path.with_suffix(env_path.suffix + f".bak.{ts}")
    try:
        bak.write_bytes(env_path.read_bytes())
    except Exception as e:
        report.log_fail(f"Backup .env fallito (docker paths): {e}")
        return 3

    out_lines: list[str] = []
    seen: set[str] = set()
    for k, v, raw in entries:
        if not k:
            out_lines.append(raw)
            continue
        if k in seen:
            continue
        seen.add(k)
        if k in values:
            out_lines.append(f"{k}={values[k]}")
        else:
            out_lines.append(raw)
    try:
        env_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    except Exception as e:
        report.log_fail(f"Scrittura .env fallita (docker paths): {e}")
        try:
            env_path.write_bytes(bak.read_bytes())
        except Exception:
            pass
        return 4

    report.log_ok(
        f"Migrate Docker data paths: {len(actions)} rewrite(s) (backup: {bak.name})"
    )
    return 0


_WEB_SEARCH_ENV_DEFAULTS: dict[str, str] = {
    "AION_NATIVE_TOOL_REGISTRY_PATH": "config/native_tool_registry.yaml",
    "AION_NATIVE_TOOL_REGISTRY_LOCAL_PATH": "",
    "AION_WEB_SEARCH_TAVILY_ENABLED": "0",
    "AION_WEB_SEARCH_BRAVE_ENABLED": "0",
    "AION_WEB_SEARCH_SEARXNG_ENABLED": "0",
    "AION_TAVILY_API_KEY": "",
    "AION_BRAVE_SEARCH_API_KEY": "",
    "AION_SEARXNG_BASE_URL": "",
    "AION_WEB_SEARCH_DEFAULT_PROVIDER": "tavily",
    "AION_WEB_SEARCH_FALLBACK_ORDER": "brave,searxng",
    "AION_WEB_SEARCH_MAX_RESULTS": "8",
    "AION_WEB_SEARCH_TIMEOUT_SEC": "30",
    "AION_WEB_SEARCH_LANGUAGE": "",
    "AION_WEB_SEARCH_ALLOWED_HOSTS": "",
    "AION_WEB_SEARCH_ENFORCE_GLOBAL_ALLOWLIST": "0",
    "AION_WEB_SEARCH_REQUIRE_CLIENT_OPT_IN": "0",
    "AION_WEB_FETCH_TIMEOUT_SEC": "25",
    "AION_WEB_FETCH_MAX_BYTES": "2000000",
    "AION_WEB_FETCH_MAX_CHARS": "120000",
    "AION_WEB_FETCH_ALLOWLIST_REGEX": "",
    "AION_SCRAPLING_STEALTH_ENABLED": "0",
    "AION_TAVILY_SEARCH_DEPTH": "basic",
}

_SANDBOX_ENV_DEFAULTS: dict[str, str] = {
    "AION_SANDBOX_AUTO_VENV": "1",
    "AION_SANDBOX_ALLOW_PACKAGE_INSTALL": "1",
    "AION_SANDBOX_ALLOW_NPM_INSTALL": "1",
}

_DOCKER_COMPOSE_ENV_DEFAULTS: dict[str, str] = {
    "CADDY_HTTP_PORT": "80",
    "CADDY_HTTPS_PORT": "443",
    "AION_MCP_REGISTRY_LOCAL_PATH": "/app/data/mcp_registry.local.yaml",
    "DOCKER_BUILDKIT": "1",
    "PYTHON_VERSION": "3.13-slim",
    "UV_VERSION": "latest",
}

_CRON_ENV_DEFAULTS = {
    "AION_CRON_ENABLED": "0",
    "AION_CRON_DEFAULT_TIMEZONE": "Europe/Rome",
    "AION_CRON_MAX_JOBS_PER_USER": "50",
    "AION_CRON_MISFIRE_GRACE_SEC": "300",
}

_SQL_QM_ENV_DEFAULTS: dict[str, str] = {
    "AION_SQL_QM_ENABLED": "1",
    "AION_SQL_QM_DEFAULT_PROJECT": "default",
    "AION_SQL_QM_DEFAULT_SCOPE": "per_user",
    "AION_SQL_QM_SEARCH_THRESHOLD": "0.78",
    "AION_SQL_QM_DEDUP_THRESHOLD": "0.90",
    "AION_SQL_QM_REVIEW_THRESHOLD": "0.82",
    "AION_SQL_QM_INJECT_THRESHOLD": "0.80",
    "AION_SQL_QM_AUTO_LEARN": "0",
    "AION_SQL_QM_SEARCH_BEFORE_RUN": "1",
    "AION_SQL_QM_NATIVE_TOOLS": "1",
    "AION_SQL_QM_AUTO_VERIFY_THRESHOLD": "3",
    "AION_SQL_QM_TOOL_TIMEOUT_SEC": "60",
}

_MEMPALACE_NAV_ENV_DEFAULTS: dict[str, str] = {
    "AION_MEMPALACE_NAV_ENABLED": "1",
    "AION_MEMPALACE_NAV_PRE_TURN_INJECT": "0",
    "AION_MEMPALACE_NAV_INJECT_THRESHOLD": "0.75",
    "AION_MEMPALACE_NAV_AUTO_LEARN": "0",
    "AION_MEMPALACE_PROJECT_WING_PREFIX": "wing_proj_",
    "AION_MEMPALACE_NAV_SEARCH_LIMIT": "5",
    "AION_MEMPALACE_DEDUP_THRESHOLD": "0.87",
    "AION_MEMPALACE_WEAK_MEMORY_THRESHOLD": "0.4",
    "AION_MEMPALACE_NAV_AUTO_KG": "0",
    "AION_LTM_MIN_IMPORTANCE": "2",
    "AION_AGENT_MIN_REASONING_CHARS_WITHOUT_TOOL": "2500",
    "AION_AGENT_MAX_REASONING_WITHOUT_TOOL": "0",
    "AION_SQL_QM_PARAMETERIZE": "1",
}

_MCP_POOL_ENV_DEFAULTS: dict[str, str] = {
    "AION_MCP_POOL": "1",
    "AION_MCP_USER_POOL": "1",
    "AION_MCP_SESSION_ENV_INJECT": "0",
    "AION_MCP_SESSION_SCOPED_SERVERS": (
        "session_sandbox,promo_render,ocr,ocr_mcp,skills_hub,memory,aion_subagents"
    ),
    "AION_MCP_STARTUP_WARM": "1",
    "AION_MCP_STARTUP_WARM_ASYNC": "0",
    "AION_MCP_STARTUP_WARM_PROFILES": "aion_std,generic_assistant",
    "AION_MCP_STARTUP_WARM_ALL": "0",
    "AION_MCP_STARTUP_WARM_USER_ID": "default",
    "AION_MCP_POOL_IDLE_SEC": "0",
    "AION_MCP_USER_POOL_IDLE_CLEANUP": "0",
    "AION_MCP_WARM_TIMEOUT_SEC": "10",
    "AION_MCP_LIST_TOOLS_TIMEOUT_SEC": "30",
}

_PROFILE_ENV_DEFAULTS: dict[str, str] = {
    "AION_DEFAULT_PROFILE": "aion_std",
    "AION_PROFILE_VALIDATE_STRICT": "0",
    "AION_PROFILE_HOT_RELOAD": "0",
    "AION_PROFILE_LEGACY_NAME_LOOKUP": "0",
}

_SKILL_VIEW_ENV_DEFAULTS: dict[str, str] = {
    "AION_SKILL_VIEW_ENFORCE_PROFILE": "1",
}

_SKILL_LIFECYCLE_ENV_DEFAULTS: dict[str, str] = {
    "AION_SKILL_DISTILL_TOOL_LOG_MAX_CHARS": "8000",
    "AION_SKILL_VIEW_METRICS": "1",
}

_CONTEXT_COMPRESS_ENV_DEFAULTS: dict[str, str] = {
    "AION_MODEL_MAX_CONTEXT": "131072",
    "AION_CONTEXT_COMPRESS_ENABLED": "1",
    "AION_CONTEXT_COMPRESS_THRESHOLD": "0.5",
    "AION_CONTEXT_COMPRESS_MODEL_WINDOW": "131072",
    "AION_CONTEXT_COMPRESS_KEEP_LAST": "6",
    "AION_CONTEXT_COMPRESS_MAX_ROUNDS": "3",
    "AION_CONTEXT_COMPRESS_RESERVE_OUTPUT": "1",
    "AION_CONTEXT_COMPRESS_FIXED_OVERHEAD": "4096",
}

_AGENT_MODE_ENV_DEFAULTS = {
    "AION_DEFAULT_AGENT_MODE": "normal",
    "AION_PLAN_MODE_BLOCKED_TOOLS": (
        "sandbox_write_workspace_file,sandbox_edit_workspace_file,"
        "sandbox_exec_allowlisted,sandbox_run_python_file,sandbox_run_node_file,"
        "sandbox_install_python_packages,sandbox_install_npm_packages,"
        "mark_task_completed,delegate_to_subagent,skill_view"
    ),
    "AION_PLAN_MODE_MAX_RESEARCH_TOOLS": "2",
    "AION_PLAN_MODE_RESEARCH_TOOLS": (
        "list_dir,sandbox_list_files,view_file,sandbox_read_text_file,"
        "grep_search,web_search,skill_search,skill_list"
    ),
}

_PLAN_MODE_ENV_DEFAULTS: dict[str, str] = {
    "AION_PLAN_MODE_TOOL_FIRST": "1",
    "AION_PLAN_TEXT_PARSER": "0",
    "AION_PLAN_FINALIZER_TIMEOUT_SEC": "20",
    "AION_ARTIFACT_STRATEGY": "tool",
    "AION_ORCHESTRATION_SECRET_AUTH": "1",
}

_DEEP_RESEARCH_ENV_DEFAULTS: dict[str, str] = {
    "AION_DEEP_RESEARCH_ENABLED": "1",
    "AION_DEEP_RESEARCH_MAX_ROUNDS": "8",
    "AION_DEEP_RESEARCH_MAX_TIME": "600",
    "AION_DEEP_RESEARCH_DATA_DIR": "data/deep_research",
    "AION_DEEP_RESEARCH_MAX_TOKENS": "16384",
    "AION_DEEP_RESEARCH_EXTRACTION_TIMEOUT": "90",
    "AION_DEEP_RESEARCH_EXTRACTION_CONCURRENCY": "3",
    "AION_DEEP_RESEARCH_RUN_TIMEOUT": "1800",
    "AION_DEEP_RESEARCH_MAX_CONCURRENT": "2",
}


def _warmup_chroma_embeddings(py_exec: str, *, dry_run: bool, report: Report) -> None:
    script = ROOT / "scripts" / "warmup_chroma_embeddings.py"
    if not script.is_file():
        report.log_warn("Chroma embedding warmup: script missing, skip")
        return
    rc = _run([py_exec, str(script)], dry_run=dry_run)
    if rc != 0:
        report.log_warn(
            "Chroma embedding warmup failed — first MemPalace call may download ~80MB "
            "(ensure network; or run python scripts/warmup_chroma_embeddings.py)"
        )
    else:
        report.log_ok("Chroma embedding warmup (MemPalace ONNX cache)")


def _ensure_sandbox_env_keys(env_path: Path, *, dry_run: bool, report: Report) -> int:
    """Aggiunge gate sandbox pip/npm se assenti nel .env."""
    if not env_path.is_file():
        report.log_ok("Sandbox env defaults: .env assente, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys_file = {k for k, _, _ in entries if k}
    missing = [(k, v) for k, v in _SANDBOX_ENV_DEFAULTS.items() if k not in keys_file]
    if not missing:
        report.log_ok("Sandbox env defaults: chiavi già presenti")
        return 0
    if dry_run:
        report.log_ok(
            f"Sandbox env defaults: aggiungerebbe {len(missing)} chiavi (dry-run)"
        )
        return 0
    block = (
        "\n# --- Session sandbox pip/npm (append da upgrade-aion) ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + "\n" + block,
            encoding="utf-8",
        )
    except Exception as e:
        report.log_fail(f"Sandbox env defaults: scrittura fallita: {e}")
        return 3
    report.log_ok(f"Sandbox env defaults: aggiunte {len(missing)} chiavi")
    return 0


def _ensure_docker_compose_env_keys(
    env_path: Path, *, dry_run: bool, report: Report
) -> int:
    """Aggiunge chiavi usate da docker-compose.yml se assenti nel .env."""
    if not env_path.is_file():
        report.log_ok("Docker compose env defaults: .env assente, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys_file = {k for k, _, _ in entries if k}
    missing = [
        (k, v) for k, v in _DOCKER_COMPOSE_ENV_DEFAULTS.items() if k not in keys_file
    ]
    if not missing:
        report.log_ok("Docker compose env defaults: chiavi già presenti")
        return 0
    if dry_run:
        report.log_ok(
            f"Docker compose env defaults: aggiungerebbe {len(missing)} chiavi (dry-run)"
        )
        return 0
    block = (
        "\n# --- Docker Compose / Caddy (append da upgrade-aion) ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + "\n" + block,
            encoding="utf-8",
        )
    except Exception as e:
        report.log_fail(f"Docker compose env defaults: scrittura fallita: {e}")
        return 3
    report.log_ok(f"Docker compose env defaults: aggiunte {len(missing)} chiavi")
    return 0


def _ensure_sql_qm_env_keys(env_path: Path, *, dry_run: bool, report: Report) -> int:
    if not env_path.is_file():
        report.log_ok("SQL QueryMemory env defaults: .env assente, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys_file = {k for k, _, _ in entries if k}
    missing = [(k, v) for k, v in _SQL_QM_ENV_DEFAULTS.items() if k not in keys_file]
    if not missing:
        report.log_ok("SQL QueryMemory env defaults: chiavi già presenti")
        return 0
    if dry_run:
        report.log_ok(
            f"SQL QueryMemory env defaults: aggiungerebbe {len(missing)} chiavi (dry-run)"
        )
        return 0
    block = (
        "\n# --- SQL QueryMemory (append da upgrade-aion): cache SELECT Postgres separata da PromQL ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + "\n" + block,
            encoding="utf-8",
        )
    except Exception as e:
        report.log_fail(f"SQL QueryMemory env defaults: scrittura fallita: {e}")
        return 3
    report.log_ok(f"SQL QueryMemory env defaults: aggiunte {len(missing)} chiavi")
    return 0


def _patch_sql_query_memory_config(py_exec: str, dry_run: bool, report: Report) -> None:
    patch_script = ROOT / "scripts" / "patch_sql_query_memory_config.py"
    if not patch_script.is_file():
        report.log_warn(
            "patch_sql_query_memory_config.py missing — skip profile/skill patch"
        )
        return
    if dry_run:
        report.log_ok("SQL QueryMemory config patch skipped in dry-run")
        return
    rc = _run([py_exec, str(patch_script)])
    if rc == 0:
        report.log_ok("SQL QueryMemory config (skill + postgres profile)")
    else:
        report.log_warn("SQL QueryMemory config patch exited non-zero")


def _ensure_mempalace_nav_env_keys(
    env_path: Path, *, dry_run: bool, report: Report
) -> int:
    if not env_path.is_file():
        report.log_ok("MemPalace navigation env defaults: .env assente, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys_file = {k for k, _, _ in entries if k}
    missing = [
        (k, v) for k, v in _MEMPALACE_NAV_ENV_DEFAULTS.items() if k not in keys_file
    ]
    if not missing:
        report.log_ok("MemPalace navigation env defaults: chiavi già presenti")
        return 0
    if dry_run:
        report.log_ok(
            f"MemPalace navigation env defaults: aggiungerebbe {len(missing)} chiavi (dry-run)"
        )
        return 0
    block = (
        "\n# --- MemPalace navigazione ERP (append da upgrade-aion): wing_proj_{project} allineato a SQL QM ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + "\n" + block,
            encoding="utf-8",
        )
    except Exception as e:
        report.log_fail(f"MemPalace navigation env defaults: scrittura fallita: {e}")
        return 3
    report.log_ok(f"MemPalace navigation env defaults: aggiunte {len(missing)} chiavi")
    return 0


def _ensure_mcp_pool_env_keys(env_path: Path, *, dry_run: bool, report: Report) -> int:
    if not env_path.is_file():
        report.log_ok("MCP pool env defaults: .env assente, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys_file = {k for k, _, _ in entries if k}
    missing = [(k, v) for k, v in _MCP_POOL_ENV_DEFAULTS.items() if k not in keys_file]
    if not missing:
        report.log_ok("MCP pool env defaults: chiavi già presenti")
        return 0
    if dry_run:
        report.log_ok(
            f"MCP pool env defaults: aggiungerebbe {len(missing)} chiavi (dry-run)"
        )
        return 0
    block = (
        "\n# --- MCP pool / startup warm (append da upgrade-aion) ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + "\n" + block,
            encoding="utf-8",
        )
    except Exception as e:
        report.log_fail(f"MCP pool env defaults: scrittura fallita: {e}")
        return 3
    report.log_ok(f"MCP pool env defaults: aggiunte {len(missing)} chiavi")
    return 0


def _ensure_profile_env_keys(env_path: Path, *, dry_run: bool, report: Report) -> int:
    if not env_path.is_file():
        report.log_ok("Profile env defaults: .env assente, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys_file = {k for k, _, _ in entries if k}
    missing = [(k, v) for k, v in _PROFILE_ENV_DEFAULTS.items() if k not in keys_file]
    if not missing:
        report.log_ok("Profile env defaults: chiavi già presenti")
        return 0
    if dry_run:
        report.log_ok(
            f"Profile env defaults: aggiungerebbe {len(missing)} chiavi (dry-run)"
        )
        return 0
    block = (
        "\n# --- Profili P2 (append da upgrade-aion) ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + "\n" + block,
            encoding="utf-8",
        )
    except Exception as e:
        report.log_fail(f"Profile env defaults: scrittura fallita: {e}")
        return 3
    report.log_ok(f"Profile env defaults: aggiunte {len(missing)} chiavi")
    return 0


def _ensure_skill_lifecycle_env_keys(
    env_path: Path, *, dry_run: bool, report: Report
) -> int:
    if not env_path.is_file():
        report.log_ok("Skill lifecycle env defaults: .env assente, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys_file = {k for k, _, _ in entries if k}
    missing = [
        (k, v) for k, v in _SKILL_LIFECYCLE_ENV_DEFAULTS.items() if k not in keys_file
    ]
    if not missing:
        report.log_ok("Skill lifecycle env defaults: chiavi già presenti")
        return 0
    if dry_run:
        report.log_ok(
            f"Skill lifecycle env defaults: aggiungerebbe {len(missing)} chiavi (dry-run)"
        )
        return 0
    block = (
        "\n# --- Skill lifecycle P2 (append da upgrade-aion) ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + "\n" + block,
            encoding="utf-8",
        )
    except Exception as e:
        report.log_fail(f"Skill lifecycle env defaults: scrittura fallita: {e}")
        return 3
    report.log_ok(f"Skill lifecycle env defaults: aggiunte {len(missing)} chiavi")
    return 0


def _ensure_skill_view_env_keys(
    env_path: Path, *, dry_run: bool, report: Report
) -> int:
    if not env_path.is_file():
        report.log_ok("skill_view env defaults: .env assente, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys_file = {k for k, _, _ in entries if k}
    missing = [
        (k, v) for k, v in _SKILL_VIEW_ENV_DEFAULTS.items() if k not in keys_file
    ]
    if not missing:
        report.log_ok("skill_view env defaults: chiavi già presenti")
        return 0
    if dry_run:
        report.log_ok(
            f"skill_view env defaults: aggiungerebbe {len(missing)} chiavi (dry-run)"
        )
        return 0
    block = (
        "\n# --- skills_hub profile allowlist (append da upgrade-aion) ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + "\n" + block,
            encoding="utf-8",
        )
    except Exception as e:
        report.log_fail(f"skill_view env defaults: scrittura fallita: {e}")
        return 3
    report.log_ok(f"skill_view env defaults: aggiunte {len(missing)} chiavi")
    return 0


def _patch_mempalace_navigation_config(
    py_exec: str, dry_run: bool, report: Report
) -> None:
    patch_script = ROOT / "scripts" / "patch_mempalace_navigation_config.py"
    if not patch_script.is_file():
        report.log_warn(
            "patch_mempalace_navigation_config.py missing — skip MemPalace nav patch"
        )
        return
    if dry_run:
        report.log_ok("MemPalace navigation config patch skipped in dry-run")
        return
    rc = _run([py_exec, str(patch_script), "--force-skills", "--force-profile-sync"])
    if rc == 0:
        report.log_ok("MemPalace navigation config (skills + postgres profile)")
    else:
        report.log_warn("MemPalace navigation config patch exited non-zero")


def _ensure_context_compress_env_keys(
    env_path: Path, *, dry_run: bool, report: Report
) -> int:
    if not env_path.is_file():
        report.log_ok("Context compress env defaults: .env assente, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys_file = {k for k, _, _ in entries if k}
    missing = [
        (k, v) for k, v in _CONTEXT_COMPRESS_ENV_DEFAULTS.items() if k not in keys_file
    ]
    if not missing:
        report.log_ok("Context compress env defaults: chiavi già presenti")
        return 0
    if dry_run:
        report.log_ok(
            f"Context compress env defaults: aggiungerebbe {len(missing)} chiavi (dry-run)"
        )
        return 0
    block = (
        "\n# --- Context compression (append da upgrade-aion): auto-compact STM prima del turno ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + "\n" + block,
            encoding="utf-8",
        )
    except Exception as e:
        report.log_fail(f"Context compress env defaults: scrittura fallita: {e}")
        return 3
    report.log_ok(f"Context compress env defaults: aggiunte {len(missing)} chiavi")
    return 0


def _ensure_cron_env_keys(env_path: Path, *, dry_run: bool, report: Report) -> int:
    if not env_path.is_file():
        report.log_ok("Cron env defaults: .env assente, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys_file = {k for k, _, _ in entries if k}
    missing = [(k, v) for k, v in _CRON_ENV_DEFAULTS.items() if k not in keys_file]
    if not missing:
        report.log_ok("Cron env defaults: chiavi già presenti")
        return 0
    if dry_run:
        report.log_ok(
            f"Cron env defaults: aggiungerebbe {len(missing)} chiavi (dry-run)"
        )
        return 0
    block = (
        "\n# --- Scheduled jobs (append da upgrade-aion): per-user cron in-process ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + "\n" + block,
            encoding="utf-8",
        )
    except Exception as e:
        report.log_fail(f"Cron env defaults: scrittura fallita: {e}")
        return 3
    report.log_ok(f"Cron env defaults: aggiunte {len(missing)} chiavi")
    return 0


def _ensure_plan_mode_env_keys(env_path: Path, *, dry_run: bool, report: Report) -> int:
    if not env_path.is_file():
        report.log_ok("Plan mode env defaults: .env assente, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys_file = {k for k, _, _ in entries if k}
    missing = [(k, v) for k, v in _PLAN_MODE_ENV_DEFAULTS.items() if k not in keys_file]
    for k, v, _ in entries:
        if k == "AION_ARTIFACT_STRATEGY" and (v or "").strip().lower() in (
            "plan",
            "markdown",
        ):
            if dry_run:
                report.log_ok(
                    "Plan mode: would set AION_ARTIFACT_STRATEGY=xml (was legacy)"
                )
            elif _rewrite_env_key(env_path, "AION_ARTIFACT_STRATEGY", "xml"):
                report.log_ok("Plan mode: upgraded AION_ARTIFACT_STRATEGY to xml")
            else:
                report.log_fail(
                    "Plan mode: failed to rewrite AION_ARTIFACT_STRATEGY in .env"
                )
    if not missing:
        report.log_ok("Plan mode env defaults: chiavi già presenti")
        return 0
    if dry_run:
        report.log_ok(
            f"Plan mode env defaults: aggiungerebbe {len(missing)} chiavi (dry-run)"
        )
        return 0
    block = (
        "\n# --- Plan mode tool-first (append da upgrade-aion) ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + "\n" + block,
            encoding="utf-8",
        )
    except Exception as e:
        report.log_fail(f"Plan mode env defaults: scrittura fallita: {e}")
        return 3
    report.log_ok(f"Plan mode env defaults: aggiunte {len(missing)} chiavi")
    return 0


def _warn_public_orchestration_secret(env_path: Path, *, report: Report) -> None:
    if not env_path.is_file():
        return
    for k, v, _ in _parse_env_simple(env_path):
        if k == "NEXT_PUBLIC_AION_ORCHESTRATION_INTERNAL_SECRET" and (v or "").strip():
            report.log_warn(
                "NEXT_PUBLIC_AION_ORCHESTRATION_INTERNAL_SECRET is set — "
                "orchestration approve should use chat JWT; remove this from client bundles."
            )
            return


def _ensure_agent_mode_env_keys(
    env_path: Path, *, dry_run: bool, report: Report
) -> int:
    if not env_path.is_file():
        report.log_ok("Agent mode env defaults: .env assente, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys_file = {k for k, _, _ in entries if k}
    missing = [
        (k, v) for k, v in _AGENT_MODE_ENV_DEFAULTS.items() if k not in keys_file
    ]
    if not missing:
        report.log_ok("Agent mode env defaults: chiavi già presenti")
        return 0
    if dry_run:
        report.log_ok(
            f"Agent mode env defaults: aggiungerebbe {len(missing)} chiavi (dry-run)"
        )
        return 0
    block = (
        "\n# --- Agent mode (append da upgrade-aion): modalità default agent e tool bloccati in plan mode ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + "\n" + block,
            encoding="utf-8",
        )
    except Exception as e:
        report.log_fail(f"Agent mode env defaults: scrittura fallita: {e}")
        return 3
    report.log_ok(f"Agent mode env defaults: aggiunte {len(missing)} chiavi")
    return 0


def _ensure_deep_research_env_keys(
    env_path: Path, *, dry_run: bool, report: Report
) -> int:
    if not env_path.is_file():
        report.log_ok("Deep research env defaults: .env assente, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys_file = {k for k, _, _ in entries if k}
    missing = [
        (k, v) for k, v in _DEEP_RESEARCH_ENV_DEFAULTS.items() if k not in keys_file
    ]
    if not missing:
        report.log_ok("Deep research env defaults: chiavi già presenti")
        return 0
    if dry_run:
        report.log_ok(
            f"Deep research env defaults: aggiungerebbe {len(missing)} chiavi (dry-run)"
        )
        return 0
    block = (
        "\n# --- Deep research (append da upgrade-aion): IterResearch, report HTML, tool trigger_research ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + "\n" + block,
            encoding="utf-8",
        )
    except Exception as e:
        report.log_fail(f"Deep research env defaults: scrittura fallita: {e}")
        return 3
    report.log_ok(f"Deep research env defaults: aggiunte {len(missing)} chiavi")
    return 0


def _ensure_web_search_env_keys(
    env_path: Path, *, dry_run: bool, report: Report
) -> int:
    if not env_path.is_file():
        report.log_ok("Web search env defaults: .env assente, skip")
        return 0
    entries = _parse_env_simple(env_path)
    keys_file = {k for k, _, _ in entries if k}
    missing = [
        (k, v) for k, v in _WEB_SEARCH_ENV_DEFAULTS.items() if k not in keys_file
    ]
    if not missing:
        report.log_ok("Web search env defaults: chiavi già presenti")
        return 0
    if dry_run:
        report.log_ok(
            f"Web search env defaults: aggiungerebbe {len(missing)} chiavi (dry-run)"
        )
        return 0
    block = (
        "\n# --- Web search (append da upgrade-aion): provider, fetch, allowlist org "
        "(AION_WEB_SEARCH_ALLOWED_HOSTS), enforce, client opt-in ---\n"
        + "\n".join(f"{k}={v}" for k, v in missing)
        + "\n"
    )
    try:
        env_path.write_text(
            env_path.read_text(encoding="utf-8").rstrip() + "\n" + block,
            encoding="utf-8",
        )
    except Exception as e:
        report.log_fail(f"Web search env defaults: scrittura fallita: {e}")
        return 3
    report.log_ok(f"Web search env defaults: aggiunte {len(missing)} chiavi")
    return 0


def _python_exec(base_python: str) -> str:
    py = VENV_DIR / "bin" / "python"
    if os.name == "nt":
        py = VENV_DIR / "Scripts" / "python.exe"
    return str(py if py.exists() else Path(base_python))


def _load_uv_runtime():
    import importlib.util

    path = ROOT / "scripts" / "uv_runtime.py"
    spec = importlib.util.spec_from_file_location("aion_uv_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ensure_runtime(base_python: str, dry_run: bool, report: Report) -> str:
    uv_mod = _load_uv_runtime()

    if dry_run:
        report.log_ok("Create venv / deps skipped in dry-run")
        return _python_exec(base_python)
    had_venv = uv_mod.venv_python().exists()
    py_exec = uv_mod.ensure_venv(base_python, dry_run=False)
    installer = "uv" if uv_mod.uv_available() else "pip"
    if not had_venv:
        report.log_ok(f"Created virtualenv at {VENV_DIR}")
    report.log_ok(f"Runtime dependencies aligned ({installer})")
    return py_exec


class LockManager:
    def __init__(self, lock_path: Path, stale_sec: int, yes: bool):
        self.lock_path = lock_path
        self.stale_sec = stale_sec
        self.yes = yes

    def _pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_path.exists():
            try:
                data = json.loads(self.lock_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            pid = int(data.get("pid", 0) or 0)
            started = int(data.get("started_at", 0) or 0)
            age = max(0, int(time.time()) - started) if started else self.stale_sec + 1
            stale = (not self._pid_alive(pid)) and age >= self.stale_sec
            if stale and not self.yes and sys.stdin.isatty():
                ans = (
                    input(f"Stale lock detected ({self.lock_path}). Reclaim? [y/N] ")
                    .strip()
                    .lower()
                )
                if ans not in ("y", "yes"):
                    raise SystemExit(2)
            elif not stale:
                raise SystemExit(f"Lock active: {self.lock_path}")
            self.lock_path.unlink(missing_ok=True)

        payload = {
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "started_at": int(time.time()),
        }
        self.lock_path.write_text(json.dumps(payload), encoding="utf-8")

    def release(self) -> None:
        self.lock_path.unlink(missing_ok=True)


def _confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        return False
    ans = input(f"{question} [y/N] ").strip().lower()
    return ans in ("y", "yes")


def _docker_upgrade(args, report: Report) -> int:
    """Upgrade flow per deploy Docker Compose: rebuild + restart + healthcheck."""
    compose_file = ROOT / args.compose_file
    if not compose_file.exists():
        report.log_fail(f"Compose file not found: {compose_file}")
        return 2

    env_file = ROOT / args.env_file
    if not env_file.exists():
        report.log_warn(
            f".env not found at {env_file} — copy .env.docker.example or run setup-aion-env.sh --docker"
        )

    compose_cmd = ["docker", "compose", "-f", str(compose_file)]
    docker_env = _docker_client_env(env_file if env_file.is_file() else None)

    if not args.skip_backup and not args.dry_run:
        rc = _run(
            [
                sys.executable,
                str(ROOT / "scripts/aion_backup.py"),
                "--output",
                args.backup_dir,
            ]
        )
        if rc != 0:
            report.log_fail("Backup snapshot (docker mode)")
            return rc
        report.log_ok("Backup snapshot")
    elif args.skip_backup:
        report.log_warn("Backup skipped by flag")

    # Migrazione legacy AION_CHAINLIT_* → AION_CHAT_* prima di sync_config/check.
    rc = _migrate_env_legacy_keys(
        Path(args.env_file), dry_run=args.dry_run, report=report
    )
    if rc != 0:
        return rc
    rc = _migrate_docker_data_paths_in_env(
        Path(args.env_file), dry_run=args.dry_run, report=report
    )
    if rc != 0:
        return rc
    rc = _ensure_web_search_env_keys(
        Path(args.env_file), dry_run=args.dry_run, report=report
    )
    if rc != 0:
        return rc
    rc = _ensure_context_compress_env_keys(
        Path(args.env_file), dry_run=args.dry_run, report=report
    )
    if rc != 0:
        return rc
    rc = _ensure_mcp_pool_env_keys(
        Path(args.env_file), dry_run=args.dry_run, report=report
    )
    if rc != 0:
        return rc
    rc = _ensure_profile_env_keys(
        Path(args.env_file), dry_run=args.dry_run, report=report
    )
    if rc != 0:
        return rc
    rc = _ensure_sql_qm_env_keys(
        Path(args.env_file), dry_run=args.dry_run, report=report
    )
    if rc != 0:
        return rc
    rc = _ensure_mempalace_nav_env_keys(
        Path(args.env_file), dry_run=args.dry_run, report=report
    )
    if rc != 0:
        return rc
    rc = _ensure_skill_lifecycle_env_keys(
        Path(args.env_file), dry_run=args.dry_run, report=report
    )
    if rc != 0:
        return rc
    rc = _ensure_agent_mode_env_keys(
        Path(args.env_file), dry_run=args.dry_run, report=report
    )
    if rc != 0:
        return rc
    rc = _ensure_plan_mode_env_keys(
        Path(args.env_file), dry_run=args.dry_run, report=report
    )
    if rc != 0:
        return rc
    _warn_public_orchestration_secret(Path(args.env_file), report=report)
    rc = _ensure_deep_research_env_keys(
        Path(args.env_file), dry_run=args.dry_run, report=report
    )
    if rc != 0:
        return rc
    rc = _ensure_cron_env_keys(Path(args.env_file), dry_run=args.dry_run, report=report)
    if rc != 0:
        return rc
    rc = _ensure_sandbox_env_keys(
        Path(args.env_file), dry_run=args.dry_run, report=report
    )
    if rc != 0:
        return rc
    rc = _ensure_docker_compose_env_keys(
        Path(args.env_file), dry_run=args.dry_run, report=report
    )
    if rc != 0:
        return rc

    _ensure_skill_packages(sys.executable, args.dry_run, report, force_mcp=True)
    _patch_sql_query_memory_config(sys.executable, args.dry_run, report)
    _patch_mempalace_navigation_config(sys.executable, args.dry_run, report)

    extras = ROOT / "scripts/runtime_extras_setup.py"
    if extras.is_file() and not args.dry_run:
        extras_cmd = [
            sys.executable,
            str(extras),
            "--env-file",
            str(env_file),
        ]
        if args.enable_fs_policy_dev:
            extras_cmd.append("--enable-fs-policy-dev")
        if args.skip_promo_playwright:
            extras_cmd.append("--skip-promo-playwright")
        rc = _run(extras_cmd)
        if rc != 0:
            report.log_warn(
                "Runtime extras (fs policy / promo Playwright) — "
                "in Docker install Chromium inside backend image or run setup_promo_playwright.sh on host"
            )

    _warmup_chroma_embeddings(sys.executable, dry_run=args.dry_run, report=report)

    if not args.dry_run:
        rc = _run([sys.executable, str(ROOT / "scripts/check_env_example_coverage.py")])
        if rc == 0:
            report.log_ok("Env coverage check")
        else:
            report.log_warn("Env coverage drift detected")

    # Pull (per immagini base) + build
    rc = _run(
        compose_cmd + ["pull", "--ignore-buildable", "--policy", "missing"],
        dry_run=args.dry_run,
        env=docker_env,
    )
    if rc != 0:
        report.log_warn("docker compose pull (proceeding with build)")
    rc = _run(compose_cmd + ["build", "--pull"], dry_run=args.dry_run, env=docker_env)
    if rc != 0:
        report.log_fail("docker compose build")
        return rc
    report.log_ok(
        "docker compose build (DOCKER_BUILDKIT=%s)"
        % docker_env.get("DOCKER_BUILDKIT", "1")
    )

    # Restart con recreate (gestisce config drift)
    rc = _run(
        compose_cmd + ["up", "-d", "--remove-orphans"],
        dry_run=args.dry_run,
        env=docker_env,
    )
    if rc != 0:
        report.log_fail("docker compose up -d")
        return rc
    report.log_ok("docker compose up -d")

    # Verifica stato Alembic dentro il container (le migration vengono
    # applicate automaticamente al boot dal backend tramite
    # src.data.migrations.run_migrations(), con stamp head intelligente
    # se il DB e' gia' stato bootstrappato da metadata.create_all()).
    # Qui facciamo solo un check read-only con `alembic current` per
    # confermare che il DB sia allineato alla revision HEAD.
    if not args.dry_run:
        # Lasciamo qualche secondo al backend per completare il boot/migrate
        try:
            time.sleep(3)
        except Exception:
            pass
        rc = _run(compose_cmd + ["exec", "-T", "backend", "alembic", "current"])
        if rc == 0:
            report.log_ok("Alembic state check (in container)")
        else:
            report.log_warn(
                "Alembic state check failed. Inspect with: "
                "docker compose logs backend | grep -iE 'alembic|migrat'"
            )

    # Cleanup immagini dangling (opzionale, sicuro)
    if not args.dry_run:
        rc = _run(["docker", "image", "prune", "-f"])
        if rc == 0:
            report.log_ok("Pruned dangling images")

    print("\n===== DOCKER UPGRADE SUMMARY =====")
    print(f"OK: {len(report.ok)}")
    print(f"WARN: {len(report.warn)}")
    print(f"FAIL: {len(report.fail)}")
    if report.warn:
        print("Warnings:")
        for w in report.warn:
            print(f" - {w}")
    print("Next steps:")
    print(f"  docker compose -f {compose_file.name} ps")
    print(f"  docker compose -f {compose_file.name} logs -f caddy backend")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Cross-platform upgrade orchestrator")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--with-legacy", action="store_true")
    ap.add_argument("--with-destructive", action="store_true")
    ap.add_argument("--destructive-token", default="")
    ap.add_argument("--skip-backup", action="store_true")
    ap.add_argument("--backup-dir", default=str(ROOT / "data" / "_backups"))
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    ap.add_argument("--prepare-runtime", action="store_true")
    ap.add_argument(
        "--enable-fs-policy-dev",
        action="store_true",
        help="Enable sandbox_exec_allowlisted via config/fs_policy.yaml (dev policy)",
    )
    ap.add_argument(
        "--skip-promo-playwright",
        action="store_true",
        help="Skip Playwright/Chromium install for promo_render MCP",
    )
    ap.add_argument("--stale-lock-sec", type=int, default=7200)
    ap.add_argument(
        "--docker",
        action="store_true",
        help="Upgrade mode: rebuild docker compose images + restart (instead of venv + alembic).",
    )
    ap.add_argument(
        "--compose-file",
        default="docker-compose.yml",
        help="Compose file used by --docker mode (default: docker-compose.yml).",
    )
    args = ap.parse_args()

    if args.docker:
        report = Report()
        lock = LockManager(
            ROOT / "data" / ".upgrade.lock", args.stale_lock_sec, args.yes
        )
        lock.acquire()
        try:
            return _docker_upgrade(args, report)
        finally:
            lock.release()

    report = Report()
    if args.with_destructive and not args.with_legacy:
        report.log_fail("--with-destructive richiede --with-legacy")
        return 2

    base_python = sys.executable or "python3"
    lock = LockManager(ROOT / "data" / ".upgrade.lock", args.stale_lock_sec, args.yes)
    lock.acquire()
    try:
        py_exec = _python_exec(base_python)
        if args.prepare_runtime:
            py_exec = _ensure_runtime(base_python, args.dry_run, report)

        required = [
            ROOT / "scripts/setup_core.py",
            ROOT / "scripts/sync_config.py",
            ROOT / "scripts/sync_mcp_servers.py",
            ROOT / "scripts/init_unified_db.py",
            ROOT / "scripts/check_env_example_coverage.py",
        ]
        missing = [str(p) for p in required if not p.exists()]
        if missing:
            report.log_fail(f"Missing scripts: {', '.join(missing)}")
            return 2
        report.log_ok("Preflight checks")

        if not args.skip_backup:
            rc = _run(
                [
                    py_exec,
                    str(ROOT / "scripts/aion_backup.py"),
                    "--output",
                    args.backup_dir,
                ],
                dry_run=args.dry_run,
            )
            if rc != 0:
                report.log_fail("Backup snapshot")
                return rc
            report.log_ok("Backup snapshot")
        else:
            report.log_warn("Backup skipped by flag")

        # Migrazione chiavi env legacy (AION_CHAINLIT_* → AION_CHAT_*).
        # Eseguita PRIMA di setup_core.py cosi' il setup vede i nomi nuovi.
        rc = _migrate_env_legacy_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        rc = _migrate_docker_data_paths_in_env(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        rc = _ensure_web_search_env_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        rc = _ensure_context_compress_env_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        rc = _ensure_mcp_pool_env_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        rc = _ensure_profile_env_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        rc = _ensure_sql_qm_env_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        rc = _ensure_mempalace_nav_env_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        rc = _ensure_skill_view_env_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        rc = _ensure_skill_lifecycle_env_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        rc = _ensure_agent_mode_env_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        rc = _ensure_plan_mode_env_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        _warn_public_orchestration_secret(Path(args.env_file), report=report)
        rc = _ensure_deep_research_env_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        rc = _ensure_cron_env_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        rc = _ensure_sandbox_env_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc
        rc = _ensure_docker_compose_env_keys(
            Path(args.env_file), dry_run=args.dry_run, report=report
        )
        if rc != 0:
            return rc

        _ensure_skill_packages(py_exec, args.dry_run, report, force_mcp=True)
        _patch_mempalace_navigation_config(py_exec, args.dry_run, report)
        _patch_sql_query_memory_config(py_exec, args.dry_run, report)

        extras = ROOT / "scripts/runtime_extras_setup.py"
        if extras.is_file():
            extras_cmd = [
                py_exec,
                str(extras),
                "--env-file",
                args.env_file,
            ]
            if args.dry_run:
                extras_cmd.append("--dry-run")
            if args.enable_fs_policy_dev:
                extras_cmd.append("--enable-fs-policy-dev")
            if args.skip_promo_playwright:
                extras_cmd.append("--skip-promo-playwright")
            rc = _run(extras_cmd, dry_run=args.dry_run)
            if rc != 0:
                report.log_warn(
                    "Runtime extras (fs policy / promo Playwright) exited non-zero"
                )

        setup_cmd = [
            py_exec,
            str(ROOT / "scripts/setup_core.py"),
            "--output",
            args.env_file,
        ]
        if args.dry_run:
            setup_cmd.append("--dry-run")
        if args.interactive:
            setup_cmd.append("--advanced")
        else:
            setup_cmd.append("--non-interactive")
        rc = _run(setup_cmd)
        if rc != 0:
            report.log_fail("Upgrade env")
            return rc
        report.log_ok("Upgrade env")
        _prune_junk_profile_files(dry_run=args.dry_run, report=report)

        rc = _run(
            [py_exec, str(ROOT / "scripts/init_unified_db.py")], dry_run=args.dry_run
        )
        if rc != 0:
            report.log_fail("Init unified DB + alembic + timeline backfill")
            return rc
        report.log_ok("Init unified DB + alembic + timeline backfill")

        _warmup_chroma_embeddings(py_exec, dry_run=args.dry_run, report=report)

        if not args.dry_run:
            rc = _run(
                [py_exec, str(ROOT / "scripts/seed_mcp_integration_configs.py")],
                dry_run=False,
            )
            if rc != 0:
                report.log_warn(
                    "seed_mcp_integration_configs.py exited non-zero (optional)"
                )
            else:
                report.log_ok("Seed MCP integration configs (idempotent)")

        if args.with_legacy:
            for script in (
                "migrate_to_aion_db.py",
                "migrate_fs_to_storage.py",
            ):
                rc = _run([py_exec, str(ROOT / "scripts" / script), "--dry-run"])
                if rc != 0:
                    report.log_fail(f"Legacy dry-run {script}")
                    return rc
            if not args.dry_run:
                for script in (
                    "migrate_to_aion_db.py",
                    "migrate_fs_to_storage.py",
                ):
                    rc = _run([py_exec, str(ROOT / "scripts" / script)])
                    if rc != 0:
                        report.log_fail(f"Legacy apply {script}")
                        return rc
                if args.with_destructive:
                    allowed = args.destructive_token == "UNIFY"
                    if not allowed and not args.yes and sys.stdin.isatty():
                        print(
                            "Destructive operation requested: unify_memory.py may remove legacy DB files."
                        )
                        typed = input("Type UNIFY to continue: ").strip()
                        allowed = typed == "UNIFY"
                    if not allowed:
                        report.log_fail(
                            "Destructive token missing/invalid (expected UNIFY)"
                        )
                        return 2
                    if not _confirm(
                        "Confirm destructive migration execution?", args.yes
                    ):
                        report.log_warn("Destructive migration cancelled by user")
                    else:
                        rc = _run([py_exec, str(ROOT / "scripts/unify_memory.py")])
                        if rc != 0:
                            report.log_fail("Destructive unify_memory")
                            return rc
                        report.log_ok("Destructive unify_memory")
            report.log_ok("Legacy migrations")
        else:
            report.log_ok("Legacy migrations skipped")

        rc = _run([py_exec, "-c", "import src.api.main"])
        if rc != 0:
            report.log_fail("Import check src.api.main")
            return rc
        report.log_ok("Import check src.api.main")

        if not args.dry_run:
            rc = _run([py_exec, "-m", "alembic", "current"])
            if rc != 0:
                report.log_fail("Alembic current")
                return rc
            report.log_ok("Alembic current")
        else:
            report.log_ok("Alembic current skipped in dry-run")

        rc = _run([py_exec, str(ROOT / "scripts/check_env_example_coverage.py")])
        if rc == 0:
            report.log_ok("Env coverage check")
        else:
            report.log_warn("Env coverage check reported drift")

        _ver = _read_version()
        print(f"\n===== UPGRADE SUMMARY — AION {_ver} =====")
        print(f"OK: {len(report.ok)}")

        print(f"WARN: {len(report.warn)}")
        print(f"FAIL: {len(report.fail)}")
        if report.warn:
            print("Warnings:")
            for w in report.warn:
                print(f" - {w}")
        print("Next steps:")
        print("  ./scripts/dev-api.sh                       # backend FastAPI (:8001)")
        print("  cd chat-ui && pnpm dev                     # client primario (:8003)")
        print(
            "  python scripts/bootstrap_db_navigation_mempalace.py --project default"
            "  # seed wing_proj_* (once, MCP mempalace up)"
        )
        print("  ./scripts/setup_promo_playwright.sh        # promo PNG (if skipped)")
        print("  # Exec policy dev: ./scripts/upgrade-aion.sh --enable-fs-policy-dev")
        print(
            "  # (Docker)  ./scripts/upgrade-aion.sh --docker  # DOCKER_BUILDKIT=1 + uv build args"
        )
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())

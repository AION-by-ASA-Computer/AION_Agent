#!/usr/bin/env python3
"""Shared optimal AION .env profiles, MemPalace detection, and apply helpers."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

# Marker written by migrate_mempalace_to_mnemos_env.py after a successful migration.
MNEMOS_MIGRATION_MARKER = "AION_MEMORY_STACK"

MEMPALACE_ENV_KEYS: frozenset[str] = frozenset(
    {
        "AION_MEMPALACE_DEDUP_THRESHOLD",
        "AION_MEMPALACE_NAV_AUTO_KG",
        "AION_MEMPALACE_NAV_AUTO_LEARN",
        "AION_MEMPALACE_NAV_ENABLED",
        "AION_MEMPALACE_NAV_INJECT_THRESHOLD",
        "AION_MEMPALACE_NAV_PRE_TURN_INJECT",
        "AION_MEMPALACE_NAV_SEARCH_LIMIT",
        "AION_MEMPALACE_NAV_SKIP_WHEN_SQL_INJECT",
        "AION_MEMPALACE_PROJECT_WING_PREFIX",
        "AION_MEMPALACE_WARMUP",
        "AION_MEMPALACE_WEAK_MEMORY_THRESHOLD",
        "AION_MEMPALACE_PALACE_PATH",
    }
)

# Benchmark-only keys — safe to drop from production .env (defaults live in code).
BENCHMARK_ONLY_ENV_KEYS: frozenset[str] = frozenset(
    {
        "AION_LME_V2_AGENT_PROFILE",
        "AION_LME_V2_BOILERPLATE_THRESHOLD",
        "AION_LME_V2_COMPRESS_SCOPE",
        "AION_LME_V2_DOWNLOAD_SCREENSHOTS",
        "AION_LME_V2_INGEST_BATCH_SIZE",
        "AION_LME_V2_JUDGE_MAX_TOKENS",
        "AION_LME_V2_JUDGE_PROFILE",
        "AION_LME_V2_JUDGE_TIMEOUT",
        "AION_LME_V2_LLM_JUDGE",
        "AION_LME_V2_MAX_CHUNKS_PER_TRAJ",
        "AION_LME_V2_MAX_STATES_PER_TRAJ",
        "AION_LME_V2_MAX_TRAJECTORIES",
        "AION_LME_V2_MAX_TREE_CHARS",
        "AION_LME_V2_NOTE_MAX_CHARS",
        "AION_LME_V2_QA_DISABLE_REASONING",
        "AION_LME_V2_QA_MAX_TOKENS",
        "AION_LME_V2_QA_TIMEOUT",
        "AION_LME_V2_RECALL_LIMIT",
        "AION_LME_V2_SKIP_IMAGE_QUESTIONS",
        "AION_LME_V2_SKIP_WAKE",
        "AION_LME_V2_TEXT_ONLY",
        "AION_LME_V2_TIER",
        "AION_LME_V2_UI_LABEL_LIMIT",
    }
)

# Full Mnemos LTM profile (aligned with .env.example production section).
MNEMOS_OPTIMAL: dict[str, str] = {
    "AION_LTM_WAKE_MAX_ROWS": "20",
    "AION_MNEMOS_RECALL_LIMIT": "10",
    "AION_MNEMOS_NATIVE_TOOLS": "1",
    "AION_MNEMOS_READONLY_TOOLS": "0",
    "AION_MNEMOS_RECALL_LIMIT_EXPOSED": "1",
    "AION_MNEMOS_EMBEDDING_RECALL": "1",
    "AION_MNEMOS_EMBED_ON_BULK": "1",
    "AION_MNEMOS_EMBEDDING_MIN_SCORE": "0.25",
    "AION_MNEMOS_EMBEDDING_SCAN_LIMIT": "300",
    "AION_MNEMOS_HYBRID_CANDIDATE_MULT": "3",
    "AION_MNEMOS_RANK_HALF_LIFE_DAYS": "90",
    "AION_MNEMOS_RANK_W_RECENCY": "0.3",
    "AION_MNEMOS_RANK_W_IMPORTANCE": "0.2",
    "AION_MNEMOS_DREAM_ENABLED": "1",
    "AION_MNEMOS_DREAM_HOUR": "3",
    "AION_MNEMOS_DREAM_INTERVAL_SEC": "86400",
    MNEMOS_MIGRATION_MARKER: "mnemos",
}

# Runtime tuning: harness v2, TOON tool results, offload, context compression, web tools.
OPTIMAL_RUNTIME_TUNING: dict[str, str] = {
    "AION_HARNESS_V2_MESSAGES": "1",
    "AION_HARNESS_V2_INJECTIONS": "1",
    "AION_HARNESS_V2_COMPACTION": "1",
    "AION_HARNESS_V2_PROVIDER": "1",
    "AION_HARNESS_V2_TOOLS": "1",
    "AION_HARNESS_V2_TURN": "1",
    "AION_TOOL_RESULT_FORMAT": "toon",
    "AION_TOOL_WEB_FETCH_MAX_CHARS": "48000",
    "AION_TOOL_WEB_SEARCH_MAX_CHARS": "12000",
    "AION_TOON_WEB_SEARCH_SNIPPET_CHARS": "1200",
    "AION_WEB_FETCH_OFFLOAD_MAX_CHARS": "200000",
    "AION_WEB_TOOL_COMPACT_AFTER": "4",
    "AION_TOOL_CIRCUIT_BREAKER_ENABLED": "1",
    "AION_MODEL_MAX_CONTEXT": "131072",
    "AION_CONTEXT_COMPRESS_ENABLED": "1",
    "AION_CONTEXT_COMPRESS_THRESHOLD": "0.80",
    "AION_CONTEXT_COMPRESS_MODEL_WINDOW": "131072",
    "AION_CONTEXT_COMPRESS_KEEP_LAST": "12",
    "AION_CONTEXT_COMPRESS_MAX_ROUNDS": "2",
    "AION_CONTEXT_COMPRESS_RESERVE_OUTPUT": "1",
    "AION_CONTEXT_COMPRESS_FIXED_OVERHEAD": "8192",
    "AION_CONTEXT_COMPRESS_MID_TURN": "1",
    "AION_CONTEXT_COMPRESS_MID_TURN_RATIO": "0.92",
    "AION_CONTEXT_COMPRESS_MID_TURN_MIN_SEC": "15",
    "AION_CONTEXT_COMPRESS_SUMMARY_MAX_TOKENS": "4096",
    "AION_WEB_FETCH_MAX_CHARS": "24000",
    "AION_TOOL_OFFLOAD_ENABLED": "1",
    "AION_TOOL_OFFLOAD_MIN_CHARS": "8000",
    "AION_TOOL_OFFLOAD_PREVIEW_CHARS": "1500",
    "AION_TOOL_OFFLOAD_EXCLUDE": "web_search,sandbox_read_file_chunk",
    "AION_TOOL_OFFLOAD_MAX_TOTAL_MB": "64",
    "AION_TOOL_LEDGER_ENABLED": "1",
    "AION_TOOL_LEDGER_MAX_ROWS": "60",
    "AION_TOOL_LEDGER_MAX_CHARS": "3000",
    "AION_TOOL_RESULT_MAX_CHARS": "24000",
}

# Never overwrite host / container / network identity during tuning or migration.
PROTECTED_ENV_PREFIXES: tuple[str, ...] = (
    "AION_SANDBOX_",
    "AION_PODMAN_",
    "AION_CONTAINER_",
    "NEXT_PUBLIC_",
    "COMPOSE_",
    "CADDY_",
)

PROTECTED_ENV_KEYS: frozenset[str] = frozenset(
    {
        "DOMAIN",
        "LETS_ENCRYPT_EMAIL",
        "AION_API_URL",
        "AION_API_PORT",
        "AION_API_HOST",
        "AION_FASTAPI_URL",
        "AION_PUBLIC_API_URL",
        "AION_CHAT_URL",
        "AION_ADMIN_UI_URL",
        "AION_CORS_ORIGINS",
        "AION_REDIS_URL",
        "AION_DB_URL",
        "AION_DATA_DIR",
        "AION_ENV",
        "AION_CHAT_AUTH_SECRET",
        "AION_CREDENTIAL_ENCRYPTION_KEY",
        "AION_TAVILY_API_KEY",
        "AION_BRAVE_SEARCH_API_KEY",
        "AION_EMBEDDING_URL",
        "AION_EMBEDDINGS_API_KEY",
        "AION_LLM_API_KEY",
        "AION_OCR_BASE_URL",
        "AION_MODEL",
    }
)


def parse_env_simple(path: Path) -> list[tuple[str, str, str]]:
    """Return (key, value, original_line) preserving order and comments."""
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


def env_key_map(path: Path) -> dict[str, str]:
    return {k: v for k, v, _ in parse_env_simple(path) if k}


def backup_env_file(env_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = env_path.with_suffix(env_path.suffix + f".bak.{stamp}")
    shutil.copy2(env_path, backup)
    return backup


def is_protected_env_key(key: str) -> bool:
    if key in PROTECTED_ENV_KEYS:
        return True
    return any(key.startswith(prefix) for prefix in PROTECTED_ENV_PREFIXES)


def mempalace_data_dir(root: Path) -> Path:
    return root / "data" / "mempalace"


def mnemos_migration_complete(env_path: Path) -> bool:
    values = env_key_map(env_path)
    return values.get(MNEMOS_MIGRATION_MARKER, "").strip().lower() == "mnemos"


def detect_mempalace_legacy(env_path: Path, root: Path | None = None) -> bool:
    """True when MemPalace env keys or on-disk data are still present."""
    if mnemos_migration_complete(env_path):
        return False
    root = root or ROOT
    values = env_key_map(env_path)
    if any(k in values for k in MEMPALACE_ENV_KEYS):
        return True
    mp_dir = mempalace_data_dir(root)
    if mp_dir.is_dir():
        try:
            return any(mp_dir.iterdir())
        except OSError:
            return True
    return False


def _rewrite_env_entries(
    entries: list[tuple[str, str, str]],
    *,
    set_values: dict[str, str],
    remove_keys: Iterable[str],
) -> tuple[list[str], dict[str, str]]:
    remove = set(remove_keys)
    seen: set[str] = set()
    out_lines: list[str] = []
    applied: dict[str, str] = {}
    removed: set[str] = set()

    for k, _, raw in entries:
        if not k:
            out_lines.append(raw)
            continue
        if k in seen:
            continue
        seen.add(k)
        if k in remove:
            removed.add(k)
            continue
        if k in set_values:
            out_lines.append(f"{k}={set_values[k]}")
            applied[k] = set_values[k]
            continue
        out_lines.append(raw)

    for key, value in set_values.items():
        if key in seen and key not in applied:
            continue
        if key in removed:
            continue
        if key not in seen:
            out_lines.append(f"{key}={value}")
            applied[key] = value

    return out_lines, applied


def apply_env_profile(
    env_path: Path,
    *,
    set_values: dict[str, str],
    remove_keys: Iterable[str] = (),
    dry_run: bool = False,
    skip_protected: bool = True,
) -> dict[str, object]:
    """Apply env updates; returns summary dict."""
    if not env_path.is_file():
        raise FileNotFoundError(env_path)

    filtered: dict[str, str] = {}
    skipped: list[str] = []
    for key, value in set_values.items():
        if skip_protected and is_protected_env_key(key):
            skipped.append(key)
            continue
        filtered[key] = value

    remove = [k for k in remove_keys if not (skip_protected and is_protected_env_key(k))]
    entries = parse_env_simple(env_path)
    before = env_key_map(env_path)
    out_lines, applied = _rewrite_env_entries(
        entries, set_values=filtered, remove_keys=remove
    )
    removed = [k for k in remove if k in before]

    if not dry_run:
        env_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    return {
        "applied": applied,
        "removed": removed,
        "skipped_protected": skipped,
        "dry_run": dry_run,
    }


def merge_missing_only(
    env_path: Path, defaults: dict[str, str]
) -> dict[str, str]:
    """Return key→value pairs that are absent from env_path."""
    present = env_key_map(env_path)
    return {k: v for k, v in defaults.items() if k not in present}

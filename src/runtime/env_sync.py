"""Reconcile ``data/runtime.env`` with repo ``.env`` (sparse admin overrides only)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping

logger = logging.getLogger("aion.env_sync")

RUNTIME_ENV_NAME = "runtime.env"
META_NAME = "runtime.env.meta.json"
META_VERSION = 1


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_data_dir() -> Path:
    repo_root = get_repo_root()
    default_dir = "/app/data" if os.path.exists("/.dockerenv") else "data"
    data_dir_str = os.environ.get("AION_DATA_DIR", default_dir).strip()
    data_path = Path(data_dir_str)
    if not data_path.is_absolute():
        data_path = repo_root / data_path
    return data_path


def parse_env_file(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            key = k.strip()
            val = v.strip().strip('"').strip("'")
            out[key] = val
    except OSError as exc:
        logger.error("Failed to parse env file %s: %s", path, exc)
    return out


def write_env_file(path: Path, env: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in sorted(env.items())]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_meta(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Invalid %s (%s); rebuilding metadata", path, exc)
        return {}


def _save_meta(path: Path, meta: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(meta), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_base_env(*, repo_root: Path | None = None) -> Dict[str, str]:
    """Values from ``.env`` and ``.env.local`` (repo root)."""
    root = repo_root or get_repo_root()
    base: Dict[str, str] = {}
    base.update(parse_env_file(root / ".env"))
    base.update(parse_env_file(root / ".env.local"))
    return base


def seed_base_env_from_process(base: MutableMapping[str, str]) -> None:
    """When ``.env`` is not mounted in Docker, seed from compose ``env_file`` injection."""
    if (get_repo_root() / ".env").is_file():
        return
    for key, value in os.environ.items():
        if key.startswith("AION_") and key not in base:
            base[key] = value


def load_runtime_overrides(*, data_dir: Path | None = None) -> Dict[str, str]:
    data = data_dir or get_data_dir()
    return parse_env_file(data / RUNTIME_ENV_NAME)


def load_merged_env(
    *,
    repo_root: Path | None = None,
    data_dir: Path | None = None,
) -> Dict[str, str]:
    base = load_base_env(repo_root=repo_root)
    seed_base_env_from_process(base)
    merged = dict(base)
    merged.update(load_runtime_overrides(data_dir=data_dir))
    return merged


def apply_merged_env_to_os(
    *,
    repo_root: Path | None = None,
    data_dir: Path | None = None,
    respect_process_env: bool = True,
) -> Dict[str, str]:
    """Apply merged env to ``os.environ``.

  Precedence when ``respect_process_env`` is True (default boot):
    1. Existing process env (CI, compose, pytest monkeypatch)
    2. ``.env`` / ``.env.local`` base values (fill gaps only)
    3. ``runtime.env`` admin overrides (always win)

  When ``respect_process_env`` is False (admin reload): full merged snapshot.
    """
    base = load_base_env(repo_root=repo_root)
    seed_base_env_from_process(base)
    runtime_overrides = load_runtime_overrides(data_dir=data_dir)

    if respect_process_env:
        for key, value in base.items():
            if key not in os.environ:
                os.environ[key] = value
        for key, value in runtime_overrides.items():
            os.environ[key] = value
    else:
        merged = dict(base)
        merged.update(runtime_overrides)
        for key, value in merged.items():
            os.environ[key] = value

    merged = dict(base)
    merged.update(runtime_overrides)
    return merged


def _override_entries(meta: Mapping[str, Any]) -> Dict[str, Dict[str, str]]:
    raw = meta.get("overrides")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for key, info in raw.items():
        if isinstance(info, dict):
            out[str(key)] = {str(k): str(v) for k, v in info.items()}
    return out


def reconcile_runtime_env(
    *,
    repo_root: Path | None = None,
    data_dir: Path | None = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Keep ``runtime.env`` as sparse admin overrides only.

    - Keys equal to ``.env`` are removed from ``runtime.env``.
    - Legacy full dumps are migrated on first run.
    - Admin overrides (source=admin) are preserved until explicitly changed.
    - Legacy overrides are dropped when ``.env`` changes.
    """
    root = repo_root or get_repo_root()
    data = data_dir or get_data_dir()
    runtime_path = data / RUNTIME_ENV_NAME
    meta_path = data / META_NAME

    base = load_base_env(repo_root=root)
    seed_base_env_from_process(base)

    current_runtime = parse_env_file(runtime_path)
    meta = _load_meta(meta_path)
    overrides = _override_entries(meta)
    migrated = bool(meta.get("migrated"))

    new_runtime: Dict[str, str] = {}
    new_overrides: Dict[str, Dict[str, str]] = {}

    for key, runtime_val in current_runtime.items():
        base_val = base.get(key)
        info = overrides.get(key, {})
        source = info.get("source", "legacy")

        if source == "admin":
            new_runtime[key] = runtime_val
            new_overrides[key] = {
                "source": "admin",
                "updated_at": info.get("updated_at") or _utc_now(),
            }
            continue

        if key in base and base_val == runtime_val:
            continue

        if key in base and base_val != runtime_val:
            # Stale mirror or legacy override: prefer .env when it changed.
            continue

        new_runtime[key] = runtime_val
        new_overrides[key] = {
            "source": "legacy",
            "updated_at": info.get("updated_at") or _utc_now(),
        }

    if not migrated and current_runtime:
        logger.info(
            "Migrating legacy runtime.env (%d keys) to sparse overrides",
            len(current_runtime),
        )

    report = {
        "migrated": True,
        "runtime_keys_before": len(current_runtime),
        "runtime_keys_after": len(new_runtime),
        "base_keys": len(base),
        "dry_run": dry_run,
    }

    if dry_run:
        return report

    write_env_file(runtime_path, new_runtime)
    _save_meta(
        meta_path,
        {
            "migrated": True,
            "version": META_VERSION,
            "overrides": new_overrides,
            "last_reconcile_at": _utc_now(),
        },
    )
    return report


def reconcile_runtime_env_on_boot() -> Dict[str, Any]:
    try:
        report = reconcile_runtime_env()
        if report["runtime_keys_before"] != report["runtime_keys_after"]:
            logger.info(
                "runtime.env reconciled: %d -> %d override keys",
                report["runtime_keys_before"],
                report["runtime_keys_after"],
            )
        return report
    except Exception:
        logger.exception("runtime.env reconcile failed; continuing with existing files")
        return {"error": True}


def diff_against_base(
    settings: Mapping[str, str], *, repo_root: Path | None = None
) -> Dict[str, str]:
    base = load_base_env(repo_root=repo_root)
    seed_base_env_from_process(base)
    overrides: Dict[str, str] = {}
    for key, value in settings.items():
        if not key.startswith("AION_"):
            continue
        if base.get(key) != value:
            overrides[key] = value
    return overrides


def write_admin_overrides(
    updates: Mapping[str, str],
    *,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
) -> None:
    """Persist admin UI changes as sparse runtime overrides."""
    data = data_dir or get_data_dir()
    runtime_path = data / RUNTIME_ENV_NAME
    meta_path = data / META_NAME

    runtime = load_runtime_overrides(data_dir=data)
    meta = _load_meta(meta_path)
    override_meta = _override_entries(meta)
    desired = diff_against_base(updates, repo_root=repo_root)

    for key in list(runtime.keys()):
        if key not in desired:
            runtime.pop(key, None)
            override_meta.pop(key, None)

    now = _utc_now()
    for key, value in desired.items():
        runtime[key] = value
        override_meta[key] = {"source": "admin", "updated_at": now}

    write_env_file(runtime_path, runtime)
    _save_meta(
        meta_path,
        {
            "migrated": True,
            "version": META_VERSION,
            "overrides": override_meta,
            "last_admin_write_at": now,
        },
    )


def reload_env_into_process() -> None:
    """Reload merged env into ``os.environ`` and refresh dependent singletons."""
    apply_merged_env_to_os(respect_process_env=False)
    try:
        from src.runtime.agent_fs_policy import load_fs_policy

        load_fs_policy.cache_clear()
    except Exception:
        pass
    try:
        from src.config import config

        config.load()
    except Exception:
        pass
    try:
        from src.settings import get_settings

        get_settings.cache_clear()
    except Exception:
        pass

"""
Minimal environment for session sandbox subprocesses.

Strips host secrets and most AION_* configuration before user code runs.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, Optional

_DEFAULT_ALLOWLIST = frozenset(
    {
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "HOME",
        "VIRTUAL_ENV",
        "PIP_DISABLE_PIP_VERSION_CHECK",
        "NODE_PATH",
        "PYTHONPATH",
        "PYTHONUNBUFFERED",
        "TZ",
    }
)

_DEFAULT_DENY_PREFIXES = (
    "AION_API_",
    "AION_DB_",
    "AION_CHAT_AUTH_",
    "AION_ADMIN_",
    "AION_REDIS_",
    "AION_SETUP_",
)

# Exec allowlist forwards only these AION_* keys (wren and audit-safe ids).
_EXEC_AION_ALLOWLIST = frozenset(
    {
        "AION_WREN_HOME",
        "AION_WREN_PROJECT_PATH",
        "AION_WREN_EXEC_TIMEOUT_SEC",
        "AION_CHAT_SESSION_ID",
        "AION_CURRENT_PROFILE_SLUG",
        "AION_CURRENT_USER_ID",
        "AION_CURRENT_TENANT_ID",
        "AION_DATA_DIR",
        "AION_SANDBOX_PIP_INDEX_URL",
        "AION_NODE_PATH",
    }
)


def _truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


def _parse_csv(name: str, default: Iterable[str]) -> frozenset[str]:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return frozenset(default)
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def _deny_prefixes() -> tuple[str, ...]:
    raw = (os.environ.get("AION_SANDBOX_ENV_DENY_PREFIX") or "").strip()
    if not raw:
        return _DEFAULT_DENY_PREFIXES
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def _is_denied_key(key: str, deny_prefixes: tuple[str, ...]) -> bool:
    for prefix in deny_prefixes:
        if key.startswith(prefix):
            return True
    return False


def scrub_secrets_from_env(env: Dict[str, str]) -> None:
    """
    In-place removal of host secrets from a long-lived MCP worker env.

    Subprocess sandbox runs use ``build_session_env``; this helper hardens the
    ``session_sandbox`` stdio worker when ``AION_SANDBOX_BACKEND=subprocess``.
    """
    deny_prefixes = _deny_prefixes()
    extra_exact = frozenset(
        {
            "MYSQL_PASSWORD",
            "POSTGRES_PASSWORD",
            "CLICKUP_API_TOKEN",
            "CLICKUP_TEAM_ID",
            "OPIK_API_KEY",
            "KHUB_CLIENT_SECRET",
            "REDIS_PASSWORD",
            "AION_CREDENTIAL_ENCRYPTION_KEY",
            "AION_LLM_API_KEY",
            "AION_CHAT_AUTH_SECRET",
            "AION_ORCHESTRATION_INTERNAL_SECRET",
            "AION_CHAT_UI_INTERNAL_SECRET",
            "AION_AGENT_DB_EMBED_SECRET",
            "AION_API_KEY_BOOTSTRAP",
        }
    )
    for key in list(env.keys()):
        if key in extra_exact or _is_denied_key(key, deny_prefixes):
            env.pop(key, None)


def build_session_env(
    session_id: str,
    *,
    session_root: Path,
    extra: Optional[Dict[str, str]] = None,
    venv_dir: Optional[Path] = None,
) -> Dict[str, str]:
    """
    Build a scrubbed env dict for sandbox subprocesses.

    ``HOME`` is set to the session root. ``PATH`` is inherited from the parent
    unless overridden via ``extra``.
    """
    allowlist = _parse_csv("AION_SANDBOX_ENV_ALLOWLIST", _DEFAULT_ALLOWLIST)
    deny_prefixes = _deny_prefixes()

    env: Dict[str, str] = {}
    for key in allowlist:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val

    env.setdefault("LANG", "en_US.UTF-8")
    session_root_resolved = session_root.resolve()
    env["HOME"] = str(session_root_resolved)
    env.setdefault("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
    env.setdefault("PYTHONUNBUFFERED", "1")
    # Session-only data root — never forward host ``AION_DATA_DIR`` (/app/data).
    env["AION_DATA_DIR"] = str(session_root_resolved)
    env["AION_SANDBOX_SESSION_ROOT"] = str(session_root_resolved)

    if venv_dir is not None:
        env["VIRTUAL_ENV"] = str(venv_dir.resolve())

    # Minimal PYTHONPATH: repo root for ``-m src.security.sandbox_py_runner`` only.
    repo_root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(repo_root)

    # Safe, non-secret AION_* needed for session context (no broad forward).
    for key in ("AION_CHAT_SESSION_ID", "AION_NODE_PATH", "AION_SANDBOX_PIP_INDEX_URL"):
        val = os.environ.get(key)
        if val and not _is_denied_key(key, deny_prefixes):
            env[key] = val
    if session_id:
        env["AION_CHAT_SESSION_ID"] = session_id

    if extra:
        for key, val in extra.items():
            if val is not None and not _is_denied_key(key, deny_prefixes):
                env[key] = val

    return env


def build_exec_env(
    session_id: str,
    *,
    session_root: Path,
    argv: list[str],
    repo_root: Optional[Path] = None,
) -> Dict[str, str]:
    """
    Minimal env for ``sandbox_exec_allowlisted`` — stricter than general session runs.
    """
    from ..tools.session_exec import (  # noqa: WPS433 — avoid circular at import
        _extend_path_for_exec,
        _parse_dotenv_file,
        _resolve_wren_home,
        _resolve_wren_project_home,
        _exe_matches,
    )

    env = build_session_env(session_id, session_root=session_root)
    _extend_path_for_exec(env)

    deny_prefixes = _deny_prefixes()
    for key, val in os.environ.items():
        if not key.startswith("AION_"):
            continue
        if key not in _EXEC_AION_ALLOWLIST:
            continue
        if _is_denied_key(key, deny_prefixes):
            continue
        if val and repo_root and not Path(val).is_absolute():
            try:
                cleaned = val.strip('"\'')
                resolved = (repo_root / cleaned).resolve()
                if resolved.exists():
                    val = str(resolved)
            except Exception:
                pass
        env[key] = val

    if os.name == "nt":
        win_keys = {
            "SYSTEMROOT",
            "SYSTEMDRIVE",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "COMSPEC",
            "PATHEXT",
            "HOMEDRIVE",
            "HOMEPATH",
            "USERNAME",
            "WINDIR",
        }
        for key, val in os.environ.items():
            if key.upper() in win_keys:
                env[key] = val

    if argv and _exe_matches("wren", argv[0]):
        wren_home = _resolve_wren_home()
        env["WREN_HOME"] = str(wren_home)
        project_home = _resolve_wren_project_home()
        if project_home is not None:
            env["WREN_PROJECT_HOME"] = str(project_home)
            for k, v in _parse_dotenv_file(project_home / ".env").items():
                env.setdefault(k, v)

    return env

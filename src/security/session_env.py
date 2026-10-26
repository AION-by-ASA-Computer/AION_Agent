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

# Variabili d'ambiente di sistema necessarie ai processi su Windows.
_WINDOWS_SYSTEM_KEYS = frozenset(
    {
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
)

# Server MCP stdio di terze parti (npx, uvx, mcp-remote, ...): dal backend
# ricevono solo rete, certificati, locale e configurazione dei package manager.
# Credenziali e variabili per server arrivano dal blocco ``env`` del registro.
_MCP_THIRD_PARTY_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TERM",
        "LANG",
        "LANGUAGE",
        "TZ",
        "TMPDIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "all_proxy",
        "NODE_EXTRA_CA_CERTS",
        "NODE_PATH",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "DOCKER_HOST",
    }
)
_MCP_THIRD_PARTY_ALLOW_PREFIXES = ("LC_", "UV_", "NPM_CONFIG_", "npm_config_", "PIP_")

# Segreti di firma e di bootstrap: nessun server MCP, nemmeno interno, li legge.
_MCP_SIGNING_SECRETS = frozenset(
    {
        "AION_CHAT_AUTH_SECRET",
        "AION_CHAT_UI_INTERNAL_SECRET",
        "AION_ORCHESTRATION_INTERNAL_SECRET",
        "AION_API_KEY_BOOTSTRAP",
    }
)
_MCP_SIGNING_SECRET_PREFIXES = ("AION_SETUP_",)

# Exec allowlist forwards only these AION_* keys (audit-safe ids).
_EXEC_AION_ALLOWLIST = frozenset(
    {
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
            # Rimossa (API key ora per-utente): resta qui per i .env legacy.
            "AION_API_KEY_BOOTSTRAP",
        }
    )
    for key in list(env.keys()):
        if key in extra_exact or _is_denied_key(key, deny_prefixes):
            env.pop(key, None)


def mcp_env_scrub_enabled() -> bool:
    """``AION_MCP_ENV_SCRUB=0`` ripristina l'ambiente completo (solo emergenza)."""
    return _truthy("AION_MCP_ENV_SCRUB", "1")


def build_mcp_stdio_base_env(*, first_party: bool) -> Dict[str, str]:
    """
    Ambiente di partenza per un server MCP stdio, prima delle variabili per server.

    - ``first_party`` (server Python del repository): ambiente del backend senza
      i segreti di firma, perché importano ``src.*`` e ne usano la configurazione.
    - terze parti: solo ``_MCP_THIRD_PARTY_ALLOWLIST`` (+ ``AION_MCP_ENV_ALLOWLIST``).
    """
    env = dict(os.environ)
    if not mcp_env_scrub_enabled():
        return env
    if first_party:
        for key in list(env):
            if key in _MCP_SIGNING_SECRETS or key.startswith(
                _MCP_SIGNING_SECRET_PREFIXES
            ):
                env.pop(key, None)
        return env
    allow = _MCP_THIRD_PARTY_ALLOWLIST | _parse_csv("AION_MCP_ENV_ALLOWLIST", ())
    return {
        k: v
        for k, v in env.items()
        if k in allow
        or k.startswith(_MCP_THIRD_PARTY_ALLOW_PREFIXES)
        or (os.name == "nt" and k.upper() in _WINDOWS_SYSTEM_KEYS)
    }


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
    # Prevent local script names from shadowing Python standard library modules (e.g. inspect.py, types.py)
    env["PYTHONSAFEPATH"] = "1"
    # Session-only data root — never forward host ``AION_DATA_DIR`` (/app/data).
    env["AION_DATA_DIR"] = str(session_root_resolved)
    env["AION_SANDBOX_SESSION_ROOT"] = str(session_root_resolved)

    if venv_dir is not None:
        vdir = venv_dir.resolve()
        env["VIRTUAL_ENV"] = str(vdir)
        venv_bin = vdir / ("Scripts" if os.name == "nt" else "bin")
        if venv_bin.is_dir():
            current_path = env.get("PATH", "")
            prefix = str(venv_bin)
            if prefix not in current_path.split(os.pathsep):
                env["PATH"] = (
                    f"{prefix}{os.pathsep}{current_path}" if current_path else prefix
                )

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
    venv_dir: Optional[Path] = None,
) -> Dict[str, str]:
    """
    Minimal env for ``sandbox_exec_allowlisted`` — stricter than general session runs.
    """
    from ..tools.session_exec import (  # noqa: WPS433 — avoid circular at import
        _extend_path_for_exec,
        _parse_dotenv_file,
        _exe_matches,
    )
    from ..tools.session_venv import session_venv_dir

    if venv_dir is None and session_id:
        candidate = session_venv_dir(session_id)
        if candidate.is_dir():
            venv_dir = candidate

    env = build_session_env(session_id, session_root=session_root, venv_dir=venv_dir)
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
                cleaned = val.strip("\"'")
                resolved = (repo_root / cleaned).resolve()
                if resolved.exists():
                    val = str(resolved)
            except Exception:
                pass
        env[key] = val

    if os.name == "nt":
        for key, val in os.environ.items():
            if key.upper() in _WINDOWS_SYSTEM_KEYS:
                env[key] = val

    return env

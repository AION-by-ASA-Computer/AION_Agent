"""
Venv Python per sessione sotto ``data/sessions/<id>/.venv`` e installazione pacchetti controllata (pip/uv).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from ..security.session_env import build_session_env
from ..security.session_runner import run_session_subprocess
from ..session_workspace import ensure_session_dirs, session_root

logger = logging.getLogger("aion.session_venv")

# Nome PEP-ish semplice + un gruppo extras opzionale, es. httpx[http2]
_PACKAGE_TOKEN_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?(\[[a-zA-Z0-9_,=\-]+\])?$"
)


def session_venv_dir(session_id: str) -> Path:
    return session_root(session_id) / ".venv"


def session_venv_python(session_id: str) -> Path:
    root = session_venv_dir(session_id)
    if os.name == "nt":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def session_venv_exists(session_id: str) -> bool:
    py = session_venv_python(session_id)
    return py.is_file()


def _pip_install_allowed() -> bool:
    return os.environ.get("AION_SANDBOX_ALLOW_PACKAGE_INSTALL", "1").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _auto_venv_enabled() -> bool:
    return os.environ.get("AION_SANDBOX_AUTO_VENV", "1").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _pip_timeout() -> float:
    raw = (os.environ.get("AION_SANDBOX_PIP_TIMEOUT_SEC") or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    try:
        return float(os.environ.get("AION_SANDBOX_RUN_TIMEOUT_SEC", "600"))
    except ValueError:
        return 600.0


def _pip_max_packages() -> int:
    try:
        return max(1, int(os.environ.get("AION_SANDBOX_PIP_MAX_PACKAGES", "32")))
    except ValueError:
        return 32


def _default_use_uv() -> bool:
    return os.environ.get("AION_SANDBOX_PIP_USE_UV", "0").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _validate_package_names(packages: List[str]) -> List[str]:
    out: List[str] = []
    for p in packages:
        s = (p or "").strip()
        if not s:
            continue
        if not _PACKAGE_TOKEN_RE.match(s):
            raise ValueError(f"Nome pacchetto not allowed: {s!r}")
        out.append(s)
    return out


def ensure_session_venv(session_id: str) -> Path:
    """Crea ``.venv`` sotto la sessione se assente."""
    ensure_session_dirs(session_id)
    vdir = session_venv_dir(session_id)
    py = session_venv_python(session_id)
    if py.is_file():
        return vdir
    timeout = _pip_timeout()
    argv = [sys.executable, "-m", "venv", str(vdir)]
    root = session_root(session_id)
    env = build_session_env(session_id, session_root=root)
    proc = run_session_subprocess(
        session_id,
        argv,
        cwd=str(root),
        env=env,
        timeout=timeout,
        confinement_root=root,
        confinement_mode="exec",
        confinement_executables=[Path(sys.executable)],
    )
    if proc.returncode != 0:
        err = (proc.stderr or "") + (proc.stdout or "")
        raise RuntimeError(
            f"python -m venv failed (exit {proc.returncode}): {err[:4000]}"
        )
    if not py.is_file():
        raise RuntimeError("venv creato ma interprete not found")
    logger.info("Session venv creato: %s", vdir)
    return vdir


def resolve_run_python_executable(session_id: str) -> Path:
    """
    Interprete per ``sandbox_run_python_file``: venv sessione se esiste o se auto-venv è attivo.
    """
    if session_venv_exists(session_id):
        return session_venv_python(session_id)
    if _auto_venv_enabled():
        ensure_session_venv(session_id)
        return session_venv_python(session_id)
    return Path(sys.executable)


def install_packages(
    session_id: str,
    packages: List[str],
    *,
    use_uv: Optional[bool] = None,
) -> str:
    """
    Installa pacchetti nel venv della sessione (pip o uv). Disabilitato solo se AION_SANDBOX_ALLOW_PACKAGE_INSTALL=0.
    """
    if not _pip_install_allowed():
        return (
            "Installazione pacchetti disableda (AION_SANDBOX_ALLOW_PACKAGE_INSTALL=0 "
            "nel processo che ospita il server MCP session_sandbox)."
        )
    pkgs = _validate_package_names(list(packages or []))
    if not pkgs:
        return "Error: empty package list."
    if len(pkgs) > _pip_max_packages():
        return f"Error: too many packages (max {_pip_max_packages()})."

    ensure_session_venv(session_id)
    vpy = session_venv_python(session_id)
    if not vpy.is_file():
        return "Error: interprete venv not found dopo ensure_session_venv."

    use_uv_flag = _default_use_uv() if use_uv is None else bool(use_uv)
    timeout = _pip_timeout()
    root = session_root(session_id)
    env = build_session_env(
        session_id,
        session_root=root,
        venv_dir=session_venv_dir(session_id),
        extra={"PIP_DISABLE_PIP_VERSION_CHECK": "1"},
    )

    index_url = (os.environ.get("AION_SANDBOX_PIP_INDEX_URL") or "").strip()
    extra_pip: List[str] = []
    if index_url:
        extra_pip.extend(["--index-url", index_url])

    if use_uv_flag:
        uv = shutil.which("uv")
        if not uv:
            return "Error: uv required but not on PATH."
        argv = [uv, "pip", "install", "--python", str(vpy), *extra_pip, *pkgs]
        exec_paths = [Path(uv), vpy]
    else:
        argv = [str(vpy), "-m", "pip", "install", "--no-user", *extra_pip, *pkgs]
        exec_paths = [vpy]

    vdir = session_venv_dir(session_id)
    proc = run_session_subprocess(
        session_id,
        argv,
        cwd=str(root),
        env=env,
        timeout=timeout,
        confinement_root=root,
        confinement_venv=vdir if vdir.is_dir() else None,
        confinement_mode="exec",
        confinement_executables=exec_paths,
    )

    parts = [
        f"Command: {' '.join(argv)}",
        f"Exit code: {proc.returncode}",
    ]
    if proc.stdout:
        parts.append("--- stdout ---\n" + proc.stdout)
    if proc.stderr:
        parts.append("--- stderr ---\n" + proc.stderr)
    text = "\n".join(parts)
    if proc.returncode != 0:
        return f"Installation failed:\n{text}"
    return f"OK installation in session venv.\n{text}"

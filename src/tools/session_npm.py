"""
npm install in session workspace (no exec allowlist policy).
Used for docx-js and other workspace-scoped Node dependencies.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List

from ..security.session_env import build_session_env
from ..security.session_runner import run_session_subprocess
from ..session_workspace import ensure_session_dirs, session_root

logger = logging.getLogger("aion.session_npm")

_PACKAGE_TOKEN_RE = re.compile(r"^[a-zA-Z0-9@][a-zA-Z0-9._\-/]*$")


def _npm_install_allowed() -> bool:
    return os.environ.get("AION_SANDBOX_ALLOW_NPM_INSTALL", "1").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _npm_timeout() -> float:
    raw = (os.environ.get("AION_SANDBOX_NPM_TIMEOUT_SEC") or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    try:
        return float(os.environ.get("AION_SANDBOX_RUN_TIMEOUT_SEC", "600"))
    except ValueError:
        return 600.0


def _npm_max_packages() -> int:
    try:
        return max(1, int(os.environ.get("AION_SANDBOX_NPM_MAX_PACKAGES", "16")))
    except ValueError:
        return 16


def _validate_package_names(packages: List[str]) -> List[str]:
    out: List[str] = []
    for p in packages:
        name = (p or "").strip()
        if not name or len(name) > 128:
            raise ValueError(f"Invalid package name: {p!r}")
        if not _PACKAGE_TOKEN_RE.match(name):
            raise ValueError(
                f"Package name not allowed: {name!r}. Use plain npm package names (e.g. docx)."
            )
        out.append(name)
    if not out:
        raise ValueError("packages list is empty")
    if len(out) > _npm_max_packages():
        raise ValueError(f"Too many packages (max {_npm_max_packages()})")
    return out


def workspace_dir(session_id: str) -> Path:
    ensure_session_dirs(session_id)
    ws = session_root(session_id) / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def install_npm_packages(
    session_id: str, packages: List[str], *, init_if_missing: bool = True
) -> str:
    """
    Run ``npm install <packages>`` under ``data/sessions/<id>/workspace``.
    Does not require ``sandbox_exec_allowlisted`` / exec policy.
    """
    if not _npm_install_allowed():
        return (
            "Error: npm install disabled (AION_SANDBOX_ALLOW_NPM_INSTALL=0). "
            "Use python-docx via sandbox_install_python_packages + sandbox_run_python_file."
        )

    npm_exe = shutil.which("npm")
    if not npm_exe:
        return "Error: npm not found on server PATH. Install Node.js/npm or use python-docx instead."

    try:
        pkgs = _validate_package_names(packages)
    except ValueError as e:
        return f"Validation error: {e}"

    ws = workspace_dir(session_id)
    pkg_json = ws / "package.json"
    sroot = session_root(session_id)
    env = build_session_env(session_id, session_root=sroot)
    if init_if_missing and not pkg_json.is_file():
        init = run_session_subprocess(
            session_id,
            [npm_exe, "init", "-y"],
            cwd=str(ws),
            env=env,
            timeout=min(120.0, _npm_timeout()),
            confinement_root=sroot,
            confinement_mode="exec",
            confinement_executables=[Path(npm_exe)],
        )
        if init.returncode != 0:
            tail = "\n".join(x for x in (init.stderr, init.stdout) if x).strip()[-1500:]
            return f"Error: npm init failed (exit {init.returncode}):\n{tail}"

    cmd = [npm_exe, "install", *pkgs]
    timeout = _npm_timeout()
    logger.info("npm install session=%s packages=%r cwd=%s", session_id[:8], pkgs, ws)
    try:
        proc = run_session_subprocess(
            session_id,
            cmd,
            cwd=str(ws),
            env=env,
            timeout=timeout,
            confinement_root=sroot,
            confinement_mode="exec",
            confinement_executables=[Path(npm_exe)],
        )
    except subprocess.TimeoutExpired:
        return f"Error: npm install timeout after {timeout:g}s (AION_SANDBOX_NPM_TIMEOUT_SEC)."

    if proc.returncode != 0:
        blob = "\n".join(x for x in (proc.stderr, proc.stdout) if x).strip()
        return (
            f"Error: npm install failed (exit {proc.returncode}).\n"
            f"Command: {' '.join(cmd)}\n"
            f"{blob[-3000:]}"
        )

    return (
        f"OK: installed {', '.join(pkgs)} in {ws.relative_to(session_root(session_id))}/node_modules.\n"
        f'Run scripts with sandbox_run_node_file(relative_path="workspace/<script>.js").'
    )

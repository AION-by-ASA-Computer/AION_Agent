"""
npm install in session workspace (no exec allowlist policy).
Used for docx-js and other workspace-scoped Node dependencies.

Also answers "is this package already available?" for the session sandbox tools:
``install_npm_packages`` skips packages preinstalled in the image or already in
the session workspace, and ``missing_module_hint`` turns a Node "Cannot find
module" failure into the right next step for the agent.
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


def _preinstalled_dirs() -> List[Path]:
    """Global ``node_modules`` folders listed in ``NODE_PATH``.

    The Docker images (``docker/Dockerfile.backend`` / ``Dockerfile.sandbox``)
    install the office skill libraries (docx, pptxgenjs) there and set
    ``NODE_PATH``, which ``require()`` honours and ``build_session_env`` forwards
    to the session subprocesses. Empty in a local dev setup without NODE_PATH.
    """
    raw = os.environ.get("NODE_PATH") or ""
    return [Path(p) for p in raw.split(os.pathsep) if p.strip()]


def is_preinstalled(package: str) -> bool:
    """True when ``require(package)`` already resolves from a ``NODE_PATH`` folder."""
    return any((d / package / "package.json").is_file() for d in _preinstalled_dirs())


def is_installed_in_session(session_id: str, package: str) -> bool:
    """True when an earlier install in this session put ``package`` in ``workspace/node_modules``.

    Node resolves ``require()`` from ``workspace/node_modules`` for scripts under
    ``workspace/``, so the folder itself is the session's registry of installed
    packages: a repeated ``sandbox_install_npm_packages`` call is answered from it
    instead of running ``npm install`` again. Deliberately per session: a package
    installed by one session is never made visible to other sessions or users
    (a prompt-injected install must not spread). Read-only: no folder is created.
    """
    try:
        root = session_root(session_id)
    except ValueError:
        # Invalid session id: nothing can be installed there; the install path
        # reports the error itself when it creates the workspace.
        return False
    return (root / "workspace" / "node_modules" / package / "package.json").is_file()


_MISSING_MODULE_RE = re.compile(
    r"Cannot find (?:module|package) '([^']+)'", re.IGNORECASE
)


def missing_module_hint(session_id: str, output: str) -> str:
    """Hint for the agent when ``node`` failed because a module was not found.

    Called by ``SessionSandboxExecutor.run_node_file`` on a non-zero exit whose
    output contains "Cannot find module/package". The advice depends on why the
    module was missing, so the agent does not loop on reinstalling a package that
    is already there:

    - ESM ``import`` (``ERR_MODULE_NOT_FOUND``) of an installed package: ESM
      ignores ``NODE_PATH``, so the script must use ``require()`` instead.
    - CommonJS ``require`` of an installed package: an environment problem the
      agent cannot fix by installing; it should fall back to python-docx.
    - package really missing: install it, then run again.

    Returns an empty string when the output is not a missing-module error.
    """
    match = _MISSING_MODULE_RE.search(output or "")
    if not match:
        return ""
    spec = match.group(1)
    # Relative/absolute paths are the agent's own files, not npm packages.
    if spec.startswith((".", "/")):
        return (
            f"\nHINT: the local file {spec!r} was not found; check the path relative "
            "to the script (scripts run with cwd = session root)."
        )
    # "docx/build/x" -> "docx", "@scope/pkg/x" -> "@scope/pkg"
    parts = spec.split("/")
    package = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
    installed = is_preinstalled(package) or is_installed_in_session(session_id, package)
    is_esm = (
        "err_module_not_found" in output.lower()
        or "cannot find package" in output.lower()
    )
    if installed and is_esm:
        return (
            f"\nHINT: {package!r} IS installed, but ESM `import` does not see the server's "
            f"preinstalled packages. Rewrite the script with CommonJS: "
            f'`const {{ ... }} = require("{package}");` (no `import`/`export`), then run '
            "sandbox_run_node_file again. Do NOT call sandbox_install_npm_packages."
        )
    if installed:
        return (
            f"\nHINT: {package!r} IS installed, so reinstalling will not help (do NOT call "
            "sandbox_install_npm_packages). This is a server environment problem: generate the "
            "file with python-docx via sandbox_run_python_file instead and tell the user."
        )
    return (
        f'\nHINT: install the dependency with sandbox_install_npm_packages(packages=["{package}"]), '
        "then sandbox_run_node_file again. Do not use sandbox_exec_allowlisted for Node."
    )


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

    Packages already available are skipped: preinstalled globally (see
    ``is_preinstalled``) or installed by an earlier call in this session (see
    ``is_installed_in_session``). When all of them are, nothing runs and no
    ``workspace/node_modules`` is created, so the session only holds the files the
    agent actually generates.
    """
    try:
        requested = _validate_package_names(packages)
    except ValueError as e:
        return f"Validation error: {e}"
    preinstalled = [p for p in requested if is_preinstalled(p)]
    in_session = [
        p
        for p in requested
        if p not in preinstalled and is_installed_in_session(session_id, p)
    ]
    if len(preinstalled) + len(in_session) == len(requested):
        notes = []
        if preinstalled:
            notes.append(
                f"{', '.join(preinstalled)} already preinstalled on the server"
            )
        if in_session:
            notes.append(f"{', '.join(in_session)} already installed in this session")
        return (
            f"OK: {'; '.join(notes)}, nothing to install. Load them with require().\n"
            f'Run scripts with sandbox_run_node_file(relative_path="workspace/<script>.js").'
        )
    packages = [p for p in requested if p not in preinstalled and p not in in_session]

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
            [npm_exe, "init", "-y", "--cache", "/tmp/.npm-cache"],
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

    cmd = [npm_exe, "install", "--cache", "/tmp/.npm-cache", *pkgs]
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

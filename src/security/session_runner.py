"""
Unified subprocess runner for session sandbox operations.

Backends: subprocess (default dev), container (Podman/Docker).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Literal, Optional, Sequence

logger = logging.getLogger("aion.security")

ConfinementMode = Literal["python", "exec", "off"]


class SandboxBackendUnavailable(RuntimeError):
    """Raised when fail-closed is enabled and the requested backend is missing."""


def sandbox_backend() -> str:
    raw = (os.environ.get("AION_SANDBOX_BACKEND") or "subprocess").strip().lower()
    if raw in ("subprocess", "none", "container"):
        return raw
    if raw == "openshell":
        logger.warning(
            "AION_SANDBOX_BACKEND=openshell is deprecated; use subprocess or container"
        )
        return "subprocess"
    return "subprocess"


def fail_closed() -> bool:
    return os.environ.get("AION_SANDBOX_FAIL_CLOSED", "1").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _in_sandbox_container() -> bool:
    return (
        os.environ.get("AION_DATA_DIR", "").strip() == "/session"
        or os.environ.get("AION_SANDBOX_IN_CONTAINER", "").lower()
        in ("1", "true", "yes")
    )


def _maybe_wrap_confined(
    argv: List[str],
    env: dict,
    *,
    confinement_root: Optional[Path],
    confinement_venv: Optional[Path],
    confinement_mode: ConfinementMode,
    confinement_executables: Optional[Sequence[Path]] = None,
) -> List[str]:
    if confinement_mode == "off" or confinement_root is None:
        return argv
    if _in_sandbox_container():
        return argv

    from .session_confinement import confinement_enabled, stamp_confinement_env, wrap_confined_argv

    if not confinement_enabled():
        return argv

    executables: list[Path] = list(confinement_executables or ())
    if argv:
        executables.append(Path(argv[0]))
    stamp_confinement_env(
        env,
        confinement_root,
        venv_dir=confinement_venv,
        executables=executables or None,
    )
    wrapper = Path(sys.executable)
    if confinement_mode == "python" and confinement_executables:
        for exe in confinement_executables:
            if "python" in Path(exe).name.lower():
                wrapper = Path(exe)
                break
    return wrap_confined_argv(wrapper, argv, mode=confinement_mode)


def run_session_subprocess(
    session_id: str,
    argv: List[str],
    *,
    cwd: str,
    env: Optional[dict] = None,
    timeout: Optional[float] = None,
    stdin=subprocess.DEVNULL,
    confinement_root: Optional[Path] = None,
    confinement_venv: Optional[Path] = None,
    confinement_mode: ConfinementMode = "exec",
    confinement_executables: Optional[Sequence[Path]] = None,
) -> subprocess.CompletedProcess:
    """
    Execute ``argv`` under the configured sandbox backend.

    When ``AION_SANDBOX_BACKEND=subprocess``, wraps execution with
    ``sandbox_subprocess_entry`` (Landlock + optional Python guards).

    ``confinement_mode``:
      - ``exec`` — Landlock then ``execvp`` (Node, pip, npm, …)
      - ``python`` — Landlock + Python guards + ``runpy`` (user scripts)
      - ``off`` — no wrapper (internal bootstrap only)
    """
    backend = sandbox_backend()
    run_env = dict(env or {})

    if backend == "subprocess" and confinement_mode != "off":
        argv = _maybe_wrap_confined(
            list(argv),
            run_env,
            confinement_root=confinement_root,
            confinement_venv=confinement_venv,
            confinement_mode=confinement_mode,
            confinement_executables=confinement_executables,
        )

    if backend == "container":
        if _in_sandbox_container():
            return subprocess.run(
                argv,
                cwd=cwd,
                env=run_env,
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=stdin,
            )
        if fail_closed() and not _container_runtime_available():
            raise SandboxBackendUnavailable(
                "AION_SANDBOX_BACKEND=container but container runtime is not available"
            )
        return subprocess.run(
            argv,
            cwd=cwd,
            env=run_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=stdin,
        )

    return subprocess.run(
        argv,
        cwd=cwd,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=stdin,
    )


def _container_runtime_available() -> bool:
    try:
        from .container_runtime import get_container_runtime

        return get_container_runtime().is_available()
    except Exception:
        return False

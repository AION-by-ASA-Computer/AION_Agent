"""
Unified confined subprocess entrypoint.

Modes:

- ``--python <script.py> [args]`` — Landlock + Python guards + ``runpy``
- ``-- <exe> [args]`` — Landlock then ``execvp`` (Node, pip, npm, venv, …)

Landlock rules persist across ``execvp`` on Linux. Node also loads
``sandbox_node_hook.cjs`` (``--require``) so FS access is blocked even when
Landlock is unavailable in the container runtime.
"""

from __future__ import annotations

import os
import platform
import runpy
import sys
from pathlib import Path


def _session_root() -> Path:
    raw = (os.environ.get("AION_SANDBOX_SESSION_ROOT") or "").strip()
    if not raw:
        print("sandbox entry: AION_SANDBOX_SESSION_ROOT is required", file=sys.stderr)
        raise SystemExit(2)
    return Path(raw).resolve()


def _venv_dir() -> Path | None:
    raw = (os.environ.get("VIRTUAL_ENV") or "").strip()
    return Path(raw).resolve() if raw else None


def _landlock_abort_if_required() -> None:
    from .session_confinement import confinement_enabled, landlock_required

    if (
        platform.system() != "Linux"
        or not confinement_enabled()
        or not landlock_required()
    ):
        return
    print(
        "sandbox entry: Landlock required (AION_SANDBOX_LANDLOCK_REQUIRED=1) "
        "but unavailable on this kernel/container",
        file=sys.stderr,
    )
    raise SystemExit(126)


def _apply_landlock() -> bool:
    from .session_confinement import apply_landlock_from_environ

    ok = bool(apply_landlock_from_environ())
    if not ok:
        _landlock_abort_if_required()
    return ok


def _run_python_script(script_args: list[str]) -> int:
    if not script_args:
        print("usage: ... --python <script.py> [args...]", file=sys.stderr)
        return 2

    script = Path(script_args[0]).resolve()
    if not script.is_file():
        print(f"sandbox entry: script not found: {script}", file=sys.stderr)
        return 2
    if not str(script).endswith(".py"):
        print(
            f"sandbox entry: expected a .py script, got: {script}",
            file=sys.stderr,
        )
        return 2

    session_root = _session_root()
    venv_dir = _venv_dir()

    _apply_landlock()
    from .session_confinement import activate_python_guards

    activate_python_guards(session_root, venv_dir=venv_dir)

    sys.argv = [str(script), *script_args[1:]]
    runpy.run_path(str(script), run_name="__main__")
    return 0


def _exec_confined(exec_args: list[str]) -> int:
    if not exec_args:
        print("usage: ... -- <exe> [args...]", file=sys.stderr)
        return 2

    from .session_confinement import (
        confinement_enabled,
        inject_node_hook,
        landlock_required,
    )
    from .session_confinement import _paths_from_env

    exec_args = inject_node_hook(list(exec_args))
    landlock_ok = _apply_landlock()
    exe_path = exec_args[0]
    try:
        os.execvp(exe_path, list(exec_args))
    except FileNotFoundError:
        print(f"sandbox entry: executable not found: {exe_path!r}", file=sys.stderr)
        return 127
    except PermissionError as exc:
        try:
            real_exe = str(Path(exe_path).resolve())
        except OSError as resolve_exc:
            real_exe = f"<unresolvable: {resolve_exc}>"
        try:
            parent_exe = str(Path(real_exe).parent)
        except OSError:
            parent_exe = "<unresolvable>"
        x_ok = os.access(exe_path, os.X_OK)
        ll_read = _paths_from_env("AION_SANDBOX_LL_READ")
        ll_write = _paths_from_env("AION_SANDBOX_LL_WRITE")
        if ll_read:
            try:
                resolved = Path(real_exe).resolve()
                in_read = any(
                    str(resolved) == str(p.resolve())
                    or str(resolved).startswith(str(p.resolve()) + "/")
                    for p in ll_read
                    if p.resolve() and p.exists()
                )
            except OSError:
                in_read = False
        else:
            in_read = None
        print(f"sandbox entry: exec denied: {exc} (errno={exc.errno})", file=sys.stderr)
        print(
            f"  exe={exe_path!r} realpath={real_exe!r} x_ok={x_ok}",
            file=sys.stderr,
        )
        print(
            f"  parent={parent_exe!r} parent_in_ll_read={in_read}",
            file=sys.stderr,
        )
        print(
            f"  platform={platform.system()} python={sys.version.split()[0]} "
            f"confinement_enabled={confinement_enabled()} "
            f"landlock_required={landlock_required()} "
            f"landlock_applied={landlock_ok}",
            file=sys.stderr,
        )
        ll_read_str = ":".join(str(p) for p in ll_read) or "<empty>"
        ll_write_str = ":".join(str(p) for p in ll_write) or "<empty>"
        print(f"  AION_SANDBOX_LL_READ={ll_read_str}", file=sys.stderr)
        print(f"  AION_SANDBOX_LL_WRITE={ll_write_str}", file=sys.stderr)
        return 126
    return 127


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(
            "usage: python -m src.security.sandbox_subprocess_entry "
            "--python <script.py> | -- <exe> [args...]",
            file=sys.stderr,
        )
        return 2

    if args[0] == "--python":
        return _run_python_script(args[1:])
    if args[0] == "--":
        return _exec_confined(args[1:])
    # Legacy: bare script path (compat with sandbox_py_runner)
    if args[0].endswith(".py"):
        return _run_python_script(args)
    return _exec_confined(args)


if __name__ == "__main__":
    raise SystemExit(main())

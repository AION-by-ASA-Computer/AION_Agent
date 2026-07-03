"""
Executor subprocess con allowlist argv (FASE B2).
NON usa shell=True. NON accetta stringhe di comando free-form.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import pwd
except ImportError:
    pwd = None

from ..security.session_env import build_exec_env
from ..security.session_runner import run_session_subprocess
from ..runtime.agent_fs_policy import get_policy
from ..session_workspace import safe_resolve, session_root

logger = logging.getLogger("aion.session_exec")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _parse_dotenv_file(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip()] = val.strip()
    return out


def _resolve_wren_project_home() -> Optional[Path]:
    raw = (os.environ.get("AION_WREN_PROJECT_PATH") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return path.resolve()


_SYNTHETIC_HOME_MARKERS = (
    "/data/sessions/",
    "/data/users/",
    "/mcp_home",
    "\\data\\sessions\\",
    "\\data\\users\\",
    "\\mcp_home",
)


def _is_synthetic_home(home: str) -> bool:
    norm = home.replace("\\", "/").lower()
    return any(marker.replace("\\", "/") in norm for marker in _SYNTHETIC_HOME_MARKERS)


def _system_user_home() -> Path:
    if pwd is not None and hasattr(os, "getuid"):
        try:
            return Path(pwd.getpwuid(os.getuid()).pw_dir).expanduser().resolve()
        except (KeyError, OSError, AttributeError):
            pass
    return Path.home().expanduser().resolve()


def _resolve_wren_home() -> Path:
    """Wren profiles live under WREN_HOME — never under session or MCP-isolated HOME."""
    for key in ("WREN_HOME", "AION_WREN_HOME"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()

    repo_wren = (_REPO_ROOT / "data" / "wren" / ".wren").resolve()
    if (repo_wren / "profiles.yml").is_file():
        return repo_wren

    proc_home = (os.environ.get("HOME") or "").strip()
    if proc_home and not _is_synthetic_home(proc_home):
        return (Path(proc_home).expanduser() / ".wren").resolve()

    return (_system_user_home() / ".wren").resolve()


def _extend_path_for_exec(env: Dict[str, str]) -> None:
    """Prefer repo .venv/bin (or Scripts on Windows) so MCP subprocesses find wren without global install."""
    extra: list[str] = []
    venv_bin = _REPO_ROOT / ".venv" / "bin"
    if venv_bin.is_dir():
        extra.append(str(venv_bin))
    venv_scripts = _REPO_ROOT / ".venv" / "Scripts"
    if venv_scripts.is_dir():
        extra.append(str(venv_scripts))
    current = env.get("PATH", "")
    for prefix in extra:
        if prefix and prefix not in current.split(os.pathsep):
            current = f"{prefix}{os.pathsep}{current}" if current else prefix
    env["PATH"] = current


def _wren_exec_timeout_sec(requested: float) -> float:
    if requested != 30.0:
        return requested
    raw = (os.environ.get("AION_WREN_EXEC_TIMEOUT_SEC") or "180").strip()
    try:
        return max(30.0, float(raw))
    except ValueError:
        return 180.0


def _build_exec_env(sid: str, argv: List[str]) -> Dict[str, str]:
    cwd = str(session_root(sid))
    env: Dict[str, str] = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": cwd,
        "LANG": "en_US.UTF-8",
        "PYTHONUTF8": "1",
    }
    _extend_path_for_exec(env)
    for k, v in os.environ.items():
        if k.startswith("AION_"):
            if v and not Path(v).is_absolute():
                try:
                    cleaned_v = v.strip("\"'")
                    resolved_path = (_REPO_ROOT / cleaned_v).resolve()
                    if resolved_path.exists():
                        v = str(resolved_path)
                except Exception:
                    pass
            env[k] = v
    if os.name == "nt":
        # Forward essential Windows environment variables to avoid python/DLL hangs and pathlib failures
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
        for k, v in os.environ.items():
            if k.upper() in win_keys:
                env[k] = v
    if not _exe_matches("wren", argv[0]):
        return env
    wren_home = _resolve_wren_home()
    env["WREN_HOME"] = str(wren_home)
    project_home = _resolve_wren_project_home()
    if project_home is not None:
        env["WREN_PROJECT_HOME"] = str(project_home)
        for key, val in _parse_dotenv_file(project_home / ".env").items():
            env.setdefault(key, val)
    logger.debug(
        "wren_exec_env session=%s WREN_HOME=%s WREN_PROJECT_HOME=%s PATH_head=%s",
        sid[:8],
        env.get("WREN_HOME"),
        env.get("WREN_PROJECT_HOME"),
        (env.get("PATH") or "").split(os.pathsep)[:3],
    )
    return env


def _exec_failure_payload(
    *,
    argv: List[str],
    error: str,
    message: str,
    exit_code: int | None = None,
    stdout: str = "",
    stderr: str = "",
) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": error,
        "message": message,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "command": argv,
    }


class ExecDeniedError(Exception):
    """L'esecuzione è bloccata dalla policy."""


class ExecAllowlistError(Exception):
    """Il comando non è in allowlist."""


def _exe_matches(allowed_exe: str, argv0: str) -> bool:
    if not allowed_exe or not argv0:
        return False
    a = allowed_exe.strip()
    b = argv0.strip()
    if a == b:
        return True
    return os.path.basename(a) == os.path.basename(b)


def _validate_argv_against_allowlist(
    argv: List[str],
    allowlist: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not argv:
        raise ExecAllowlistError("empty argv")

    exe = argv[0]

    for entry in allowlist:
        allowed_exe = str(entry.get("executable", ""))
        if not _exe_matches(allowed_exe, exe):
            continue

        prefix = entry.get("argv_prefix") or []
        if prefix:
            if len(argv) < len(prefix) + 1:
                continue
            if argv[1 : 1 + len(prefix)] != prefix:
                continue

        return entry

    raise ExecAllowlistError(
        f"Executable {exe!r} non in allowlist. "
        "Contatta il team per aggiungere binari alla policy exec.allowlist."
    )


_PYTHON_BINARIES = frozenset(
    {"python", "python3", "python3.11", "python3.12", "python3.13"}
)


def _validate_python_argv(argv: List[str]) -> None:
    """Block inline execution; require a script path as argv[1] (docx/office helpers)."""
    if len(argv) < 2:
        raise ExecAllowlistError(
            "python requires at least the script as the first argument"
        )
    script = argv[1]
    if script in ("-c", "-m") or (
        script.startswith("-") and not script.startswith("--")
    ):
        raise ExecAllowlistError(
            "python -c / -m not allowed in exec allowlist; "
            "use sandbox_run_python_file per codice arbitrario."
        )
    if not (
        script.startswith("scripts/")
        or script.startswith("workspace/")
        or script.startswith("uploads/")
        or script.startswith("derived/")
    ):
        raise ExecAllowlistError(
            f"Script python {script!r} must be under scripts/, workspace/, uploads/ o derived/"
        )


def _validate_path_args(
    argv: List[str],
    sid: str,
    path_positions: List[int],
) -> None:
    session_r = session_root(sid)
    for pos in path_positions:
        if pos >= len(argv):
            continue
        arg = argv[pos]
        if arg.startswith("-"):
            continue
        arg_path = Path(arg)
        if arg_path.is_absolute():
            try:
                arg_path.resolve().relative_to(session_r.resolve())
            except ValueError as err:
                raise ExecAllowlistError(
                    f"Argomento path {arg!r} (posizione {pos}) is outside the session."
                ) from err
        else:
            try:
                safe_resolve(sid, arg, must_exist=False)
            except ValueError as e:
                raise ExecAllowlistError(f"Argomento path invalid: {e}") from e


def run_allowlisted(
    sid: str,
    argv: List[str],
    *,
    timeout_sec: float = 30.0,
    capture_output: bool = True,
) -> Dict[str, Any]:
    argv = list(argv)
    policy = get_policy()

    if not policy.exec_is_enabled():
        raise ExecDeniedError(
            "Esecuzione exec disabled (exec.enabled=false nella policy). "
            "Imposta AION_FS_POLICY_PATH su una policy con exec.enabled=true dopo audit."
        )

    allowlist = policy.get_exec_allowlist()
    entry = _validate_argv_against_allowlist(argv, allowlist)

    exe_base = os.path.basename(argv[0]).lower()
    if exe_base in _PYTHON_BINARIES or exe_base.startswith("python3."):
        _validate_python_argv(argv)

    path_positions = entry.get("validate_path_positions") or []
    if path_positions:
        _validate_path_args(argv, sid, path_positions)

    if _exe_matches("wren", argv[0]):
        timeout_sec = _wren_exec_timeout_sec(timeout_sec)

    cwd = str(session_root(sid))
    if len(argv) >= 2 and argv[1].startswith("scripts/"):
        script_path = session_root(sid) / argv[1]
        if not script_path.is_file():
            hint = ""
            if "office/" in argv[1]:
                hint = (
                    " Run skill_view first('docx') o "
                    "sandbox_materialize_skill_scripts(skill='docx')."
                )
            return {
                "ok": False,
                "error": "missing_script",
                "message": f"Script not found in sessione: {argv[1]}.{hint}",
                "command": argv,
            }
    env_minimal = build_exec_env(
        sid, session_root=session_root(sid), argv=argv, repo_root=_REPO_ROOT
    )

    import shutil

    resolved_exe = shutil.which(argv[0], path=env_minimal.get("PATH"))
    if resolved_exe:
        argv[0] = resolved_exe

    logger.info(
        "exec_allowlisted session=%s argv=%r",
        sid[:8],
        argv,
    )

    try:
        proc = run_session_subprocess(
            sid,
            argv,
            cwd=cwd,
            env=env_minimal,
            timeout=timeout_sec,
            stdin=subprocess.DEVNULL,
            confinement_root=session_root(sid),
            confinement_mode="exec",
            confinement_executables=[Path(argv[0])] if argv else None,
        )
    except subprocess.TimeoutExpired as exc:
        payload = _exec_failure_payload(
            argv=argv,
            error="timeout",
            message=f"Command terminated due to timeout ({timeout_sec}s)",
            stderr=(exc.stderr or "")[:10_000] if exc.stderr else "",
        )
        logger.warning(
            "exec_allowlisted timeout session=%s argv=%r timeout_sec=%s",
            sid[:8],
            argv,
            timeout_sec,
        )
        return payload
    except FileNotFoundError:
        payload = _exec_failure_payload(
            argv=argv,
            error="not_found",
            message=f"Executable not found: {argv[0]}",
        )
        logger.warning(
            "exec_allowlisted not_found session=%s argv=%r PATH=%s",
            sid[:8],
            argv,
            env_minimal.get("PATH", "")[:200],
        )
        return payload

    max_out = 50_000
    stdout = proc.stdout[:max_out] if proc.stdout else ""
    stderr = proc.stderr[:10_000] if proc.stderr else ""
    truncated = len(proc.stdout or "") > max_out

    if proc.returncode != 0:
        detail = (stderr or stdout or "").strip()
        message = detail or f"exit code {proc.returncode}"
        logger.warning(
            "exec_allowlisted failed session=%s argv=%r exit_code=%s stderr=%r stdout_head=%r",
            sid[:8],
            argv,
            proc.returncode,
            stderr[:500],
            stdout[:200],
        )
        return _exec_failure_payload(
            argv=argv,
            error="exec_failed",
            message=message,
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return {
        "ok": True,
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": truncated,
        "command": argv,
    }

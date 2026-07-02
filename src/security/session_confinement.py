"""
Filesystem confinement for session sandbox subprocesses (``AION_SANDBOX_BACKEND=subprocess``).

Strategy (defense in depth):

1. **Landlock** (Linux): deny-by-default before ``exec``; rules persist into Node/pip/npm.
2. **Python guards**: hook ``open``, ``os.*``, ``pathlib``, ``glob``, ``sqlite3`` for macOS dev.
3. **Node hook** (``sandbox_node_hook.cjs``): ``--require`` preload blocks ``/proc/*`` (except
   ``/proc/self``) and paths outside ``AION_SANDBOX_LL_*`` when Landlock is unavailable.
4. **Unified entry** (``sandbox_subprocess_entry``): apply Landlock then ``execvp`` or ``runpy``.

Env keys stamped by ``stamp_confinement_env``:

- ``AION_SANDBOX_SESSION_ROOT``
- ``AION_SANDBOX_LL_READ`` — ``:``-separated absolute paths (read/execute)
- ``AION_SANDBOX_LL_WRITE`` — ``:``-separated absolute paths (write)
"""

from __future__ import annotations

import builtins
import glob as glob_module
import logging
import os
import platform
import sqlite3
import sys
import sysconfig
from pathlib import Path
from typing import Callable, Optional, Sequence

logger = logging.getLogger("aion.security.confinement")

_SANDBOX_DENIED_PREFIXES = (
    "/proc/",
    "/sys/",
)

# Populated after activate_python_guards()
_ALLOWED_READ: tuple[Path, ...] = ()
_ALLOWED_WRITE: tuple[Path, ...] = ()
_ACTIVE = False
_GUARD_ORIGINALS: dict[str, object] = {}


def confinement_enabled() -> bool:
    raw = (os.environ.get("AION_SANDBOX_SUBPROCESS_CONFINE") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def landlock_required() -> bool:
    raw = (os.environ.get("AION_SANDBOX_LANDLOCK_REQUIRED") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def node_hook_path() -> Path:
    return Path(__file__).resolve().parent / "sandbox_node_hook.cjs"


def is_node_executable(exe: os.PathLike[str] | str) -> bool:
    return "node" in Path(exe).name.lower()


def inject_node_hook(exec_args: list[str]) -> list[str]:
    """Prepend ``node -r sandbox_node_hook.cjs`` for confined Node exec."""
    if not exec_args or not is_node_executable(exec_args[0]):
        return exec_args
    if "-r" in exec_args or "--require" in exec_args:
        return exec_args
    hook = node_hook_path()
    if not hook.is_file():
        logger.warning("Node sandbox hook missing: %s", hook)
        return exec_args
    return [exec_args[0], "-r", str(hook), *exec_args[1:]]


def _is_under(parent: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    else:
        return True


def _normalize_path(raw: os.PathLike[str] | str | bytes) -> Optional[Path]:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8", "surrogateescape")
        except Exception:
            return None
    if not isinstance(raw, (str, os.PathLike)):
        return None
    try:
        return Path(raw).resolve()
    except OSError:
        return None


def _explicitly_denied(path: Path) -> bool:
    s = str(path)
    for prefix in _SANDBOX_DENIED_PREFIXES:
        if s.startswith(prefix):
            if prefix == "/proc/" and s.startswith("/proc/self"):
                return False
            return True
    return False


def path_allowed(path: os.PathLike[str] | str | bytes, *, write: bool = False) -> bool:
    if not _ACTIVE:
        return True
    resolved = _normalize_path(path)
    if resolved is None:
        return False
    if _explicitly_denied(resolved):
        return False
    allowed = _ALLOWED_WRITE if write else _ALLOWED_READ
    for prefix in allowed:
        if _is_under(prefix, resolved):
            return True
    return False


def _dedupe_paths(paths: Sequence[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            out.append(p.resolve())
    return out


def _runtime_prefix_for_executable(exe: Path) -> Optional[Path]:
    exe = exe.resolve()
    if exe.parent.name == "bin":
        prefix = exe.parent.parent
        if prefix.is_dir():
            return prefix.resolve()
    return None


def _node_module_roots(node_exe: Path) -> list[Path]:
    roots: list[Path] = []
    node_exe = node_exe.resolve()
    roots.append(node_exe.parent)
    for candidate in (
        node_exe.parent / "lib/node_modules",
        Path("/usr/lib/node_modules"),
        Path("/usr/local/lib/node_modules"),
    ):
        if candidate.is_dir():
            roots.append(candidate.resolve())
    return roots


def collect_confinement_paths(
    session_root: Path,
    *,
    venv_dir: Optional[Path] = None,
    executables: Optional[Sequence[Path]] = None,
    extra_read: Optional[Sequence[Path]] = None,
) -> tuple[list[Path], list[Path]]:
    """Build minimal Landlock allowlists for a sandbox subprocess."""
    session_root = session_root.resolve()
    read: list[Path] = [session_root]
    write: list[Path] = [session_root]

    if venv_dir is not None and venv_dir.is_dir():
        read.append(venv_dir.resolve())

    for exe in executables or ():
        if not exe:
            continue
        exe = Path(exe)
        if not exe.is_file():
            continue
        prefix = _runtime_prefix_for_executable(exe)
        if prefix is not None:
            read.append(prefix)
        name = exe.name.lower()
        if "node" in name:
            read.extend(_node_module_roots(exe))

    # Current interpreter (wrapper / venv bootstrap).
    for attr in ("prefix", "base_prefix", "exec_prefix"):
        val = getattr(sys, attr, None)
        if val:
            p = Path(val)
            if p.exists():
                read.append(p.resolve())

    tmp = Path(os.environ.get("TMPDIR") or "/tmp")
    if tmp.exists():
        read.append(tmp.resolve())
        write.append(tmp.resolve())

    # System library dirs + dynamic linker cache: required so the kernel
    # can open ld.so / libc / libm during execve. Without these, Landlock
    # denies exec with EACCES even when the executable itself is in an
    # allowed path (the kernel open()s the dynamic linker as part of
    # execve, and that open is also Landlock-checked).
    for syslib in ("/lib", "/lib64", "/usr/lib", "/usr/lib64"):
        p = Path(syslib)
        if p.exists():
            read.append(p.resolve())
    multiarch = sysconfig.get_config_var("MULTIARCH")
    if multiarch:
        for base in ("/lib", "/usr/lib"):
            p = Path(base) / multiarch
            if p.exists():
                read.append(p.resolve())
    etc = Path("/etc")
    if etc.is_dir():
        read.append(etc.resolve())

    proc_self = Path("/proc/self")
    if proc_self.exists():
        # Keep literal /proc/self — resolve() becomes /proc/<pid> and widens Landlock rules.
        read.append(proc_self)

    if extra_read:
        for item in extra_read:
            if item.exists():
                read.append(item.resolve())

    return _dedupe_paths(read), _dedupe_paths(write)


def _paths_to_env(paths: Sequence[Path]) -> str:
    return ":".join(str(p) for p in paths)


def _paths_from_env(name: str) -> list[Path]:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return []
    out: list[Path] = []
    for part in raw.split(":"):
        part = part.strip()
        if part:
            out.append(Path(part))
    return out


def stamp_confinement_env(
    env: dict[str, str],
    session_root: Path,
    *,
    venv_dir: Optional[Path] = None,
    executables: Optional[Sequence[Path]] = None,
    extra_read: Optional[Sequence[Path]] = None,
) -> None:
    """Add Landlock path lists to a subprocess environment dict."""
    if not confinement_enabled():
        return
    read_paths, write_paths = collect_confinement_paths(
        session_root,
        venv_dir=venv_dir,
        executables=executables,
        extra_read=extra_read,
    )
    env["AION_SANDBOX_SESSION_ROOT"] = str(session_root.resolve())
    env["AION_SANDBOX_LL_READ"] = _paths_to_env(read_paths)
    env["AION_SANDBOX_LL_WRITE"] = _paths_to_env(write_paths)


def apply_landlock_from_environ() -> bool:
    """Apply Landlock using ``AION_SANDBOX_LL_*`` env vars (child entrypoint)."""
    if not confinement_enabled():
        return False
    read_paths = _paths_from_env("AION_SANDBOX_LL_READ")
    write_paths = _paths_from_env("AION_SANDBOX_LL_WRITE")
    if not read_paths:
        session_raw = (os.environ.get("AION_SANDBOX_SESSION_ROOT") or "").strip()
        if session_raw:
            read_paths, write_paths = collect_confinement_paths(Path(session_raw))
    return apply_landlock(read_paths, write_paths)


def _mount_type_for_path(path: Path) -> str:
    """Return the filesystem type of the longest mount point containing ``path``."""
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return ""
    target = str(path.resolve())
    best_mount = ""
    best_type = ""
    for line in lines:
        parts = line.split()
        if len(parts) < 7:
            continue
        mount_point = parts[4]
        sep_idx = None
        for i, tok in enumerate(parts):
            if tok == "-":
                sep_idx = i
                break
        if sep_idx is not None and sep_idx + 1 < len(parts):
            fs_type = parts[sep_idx + 1]
        else:
            fs_type = ""
        if target.startswith(mount_point) and len(mount_point) > len(best_mount):
            best_mount = mount_point
            best_type = fs_type
    return best_type


_LANDLOCK_INCOMPATIBLE_FS = frozenset({"fakeowner", "virtiofs", "osxfs", "fuse.osxfs"})


def _has_incompatible_fs(paths: Sequence[Path]) -> bool:
    for p in paths:
        if _mount_type_for_path(p) in _LANDLOCK_INCOMPATIBLE_FS:
            return True
    return False


def apply_landlock(read_paths: Sequence[Path], write_paths: Sequence[Path]) -> bool:
    if platform.system() != "Linux":
        return False
    try:
        import ctypes
    except ImportError:
        return False

    if _has_incompatible_fs(read_paths):
        logger.warning(
            "Landlock skipped: session path is on an incompatible filesystem "
            "(fakeowner/virtiofs/osxfs). Falling back to Python guards only."
        )
        return False

    LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
    LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
    LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
    LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
    LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
    LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
    LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
    LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
    LANDLOCK_RULE_PATH_BENEATH = 1

    READ = (
        LANDLOCK_ACCESS_FS_EXECUTE
        | LANDLOCK_ACCESS_FS_READ_FILE
        | LANDLOCK_ACCESS_FS_READ_DIR
    )
    WRITE = READ | (
        LANDLOCK_ACCESS_FS_WRITE_FILE
        | LANDLOCK_ACCESS_FS_REMOVE_DIR
        | LANDLOCK_ACCESS_FS_REMOVE_FILE
        | LANDLOCK_ACCESS_FS_MAKE_DIR
        | LANDLOCK_ACCESS_FS_MAKE_REG
    )

    class RulesetAttr(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    class PathBeneathAttr(ctypes.Structure):
        _fields_ = [
            ("allowed_access", ctypes.c_uint64),
            ("parent_fd", ctypes.c_int),
        ]

    libc = ctypes.CDLL(None, use_errno=True)
    syscall = libc.syscall

    def _landlock_create_ruleset(access: int) -> int:
        attr = RulesetAttr(handled_access_fs=access)
        fd = syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
        if fd < 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
        return fd

    def _landlock_add_rule(ruleset_fd: int, path: Path, access: int) -> None:
        if not path.is_dir():
            return
        fd = os.open(path, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            attr = PathBeneathAttr(allowed_access=access, parent_fd=fd)
            if (
                syscall(
                    445, ruleset_fd, LANDLOCK_RULE_PATH_BENEATH, ctypes.byref(attr), 0
                )
                != 0
            ):
                err = ctypes.get_errno()
                raise OSError(err, os.strerror(err))
        finally:
            os.close(fd)

    def _landlock_restrict_self(ruleset_fd: int) -> None:
        if syscall(446, ruleset_fd, 0) != 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))

    try:
        if hasattr(libc, "prctl"):
            # PR_SET_NO_NEW_PRIVS — required by Landlock in some container runtimes.
            if libc.prctl(38, 1, 0, 0, 0) != 0:
                err = ctypes.get_errno()
                logger.debug("prctl(PR_SET_NO_NEW_PRIVS): %s", os.strerror(err))
        ruleset_fd = _landlock_create_ruleset(READ | WRITE)
        for p in read_paths:
            _landlock_add_rule(ruleset_fd, Path(p), READ)
        for p in write_paths:
            _landlock_add_rule(ruleset_fd, Path(p), WRITE)
        _landlock_restrict_self(ruleset_fd)
        os.close(ruleset_fd)
        logger.debug(
            "Landlock active: %d read paths, %d write paths",
            len(read_paths),
            len(write_paths),
        )
        return True
    except OSError as exc:
        logger.warning("Landlock unavailable (%s); Python guards only", exc)
        return False


def _install_python_guards() -> None:
    if _GUARD_ORIGINALS:
        return

    _GUARD_ORIGINALS["builtins.open"] = builtins.open
    _GUARD_ORIGINALS["os.open"] = os.open
    _GUARD_ORIGINALS["os.listdir"] = os.listdir
    _GUARD_ORIGINALS["os.scandir"] = os.scandir
    _GUARD_ORIGINALS["os.walk"] = os.walk
    _GUARD_ORIGINALS["glob.glob"] = glob_module.glob
    _GUARD_ORIGINALS["glob.iglob"] = glob_module.iglob
    _GUARD_ORIGINALS["sqlite3.connect"] = sqlite3.connect

    orig_open = builtins.open
    orig_os_open = os.open

    def guarded_open(file, mode="r", *args, **kwargs):  # type: ignore[no-untyped-def]
        write = any(ch in str(mode) for ch in ("w", "a", "+", "x"))
        if isinstance(file, (str, bytes, os.PathLike)) and not path_allowed(
            file, write=write
        ):
            raise PermissionError(f"sandbox: filesystem access denied: {file!r}")
        return orig_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(path, int):
            return orig_os_open(path, flags, *args, **kwargs)
        write = bool(
            flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        )
        if not path_allowed(path, write=write):
            raise PermissionError(f"sandbox: filesystem access denied: {path!r}")
        return orig_os_open(path, flags, *args, **kwargs)

    builtins.open = guarded_open  # type: ignore[assignment]
    os.open = guarded_os_open  # type: ignore[assignment]

    _patch_pathlib_io()
    _patch_os_walk()
    _patch_glob()
    _patch_sqlite3()


def _patch_pathlib_io() -> None:
    from pathlib import Path as _Path

    if "Path.read_text" not in _GUARD_ORIGINALS:
        for name in (
            "read_text",
            "read_bytes",
            "write_text",
            "write_bytes",
            "open",
            "iterdir",
            "glob",
            "rglob",
        ):
            _GUARD_ORIGINALS[f"Path.{name}"] = getattr(_Path, name)

    for name, write in (
        ("read_text", False),
        ("read_bytes", False),
        ("write_text", True),
        ("write_bytes", True),
        ("open", False),
    ):
        orig = getattr(_Path, name)

        def _wrap(p: _Path, *a, _orig=orig, _write=write, **kw):  # type: ignore[no-untyped-def]
            mode = kw.get("mode", a[0] if a else "r")
            is_write = _write or any(ch in str(mode) for ch in ("w", "a", "+", "x"))
            if not path_allowed(p, write=is_write):
                raise PermissionError(f"sandbox: filesystem access denied: {p!r}")
            return _orig(p, *a, **kw)

        setattr(_Path, name, _wrap)

    orig_iterdir = _Path.iterdir
    orig_glob = _Path.glob
    orig_rglob = _Path.rglob

    def _iterdir(p: _Path):  # type: ignore[no-untyped-def]
        if not path_allowed(p):
            raise PermissionError(f"sandbox: filesystem access denied: {p!r}")
        return orig_iterdir(p)

    def _glob(p: _Path, pattern):  # type: ignore[no-untyped-def]
        if not path_allowed(p):
            raise PermissionError(f"sandbox: filesystem access denied: {p!r}")
        return orig_glob(p, pattern)

    def _rglob(p: _Path, pattern):  # type: ignore[no-untyped-def]
        if not path_allowed(p):
            raise PermissionError(f"sandbox: filesystem access denied: {p!r}")
        return orig_rglob(p, pattern)

    _Path.iterdir = _iterdir  # type: ignore[assignment]
    _Path.glob = _glob  # type: ignore[assignment]
    _Path.rglob = _rglob  # type: ignore[assignment]


def _patch_os_walk() -> None:
    orig_listdir = os.listdir
    orig_scandir = os.scandir
    orig_walk = os.walk

    def guarded_listdir(path=".", *args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(path, int):
            return orig_listdir(path, *args, **kwargs)
        if not path_allowed(path):
            raise PermissionError(f"sandbox: filesystem access denied: {path!r}")
        return orig_listdir(path, *args, **kwargs)

    def guarded_scandir(path=".", *args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(path, int):
            return orig_scandir(path, *args, **kwargs)
        if not path_allowed(path):
            raise PermissionError(f"sandbox: filesystem access denied: {path!r}")
        return orig_scandir(path, *args, **kwargs)

    def guarded_walk(top, *args, **kwargs):  # type: ignore[no-untyped-def]
        if not path_allowed(top):
            raise PermissionError(f"sandbox: filesystem access denied: {top!r}")
        return orig_walk(top, *args, **kwargs)

    os.listdir = guarded_listdir  # type: ignore[assignment]
    os.scandir = guarded_scandir  # type: ignore[assignment]
    os.walk = guarded_walk  # type: ignore[assignment]


def _patch_glob() -> None:
    for name in ("glob", "iglob"):
        orig = getattr(glob_module, name)

        def _wrap(pattern, *a, _orig=orig, **kw):  # type: ignore[no-untyped-def]
            base = os.path.dirname(pattern) or "."
            if not path_allowed(base):
                raise PermissionError(f"sandbox: filesystem access denied: {pattern!r}")
            return _orig(pattern, *a, **kw)

        setattr(glob_module, name, _wrap)


def _patch_sqlite3() -> None:
    orig_connect = sqlite3.connect

    def guarded_connect(database, *args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(database, (str, bytes, os.PathLike)) and not path_allowed(
            database
        ):
            raise PermissionError(f"sandbox: filesystem access denied: {database!r}")
        return orig_connect(database, *args, **kwargs)

    sqlite3.connect = guarded_connect  # type: ignore[assignment]


def deactivate_python_guards() -> None:
    """Restore patched builtins (tests / teardown)."""
    global _ACTIVE, _ALLOWED_READ, _ALLOWED_WRITE

    if not _GUARD_ORIGINALS:
        _ACTIVE = False
        _ALLOWED_READ = ()
        _ALLOWED_WRITE = ()
        return

    builtins.open = _GUARD_ORIGINALS["builtins.open"]  # type: ignore[assignment]
    os.open = _GUARD_ORIGINALS["os.open"]  # type: ignore[assignment]
    os.listdir = _GUARD_ORIGINALS["os.listdir"]  # type: ignore[assignment]
    os.scandir = _GUARD_ORIGINALS["os.scandir"]  # type: ignore[assignment]
    os.walk = _GUARD_ORIGINALS["os.walk"]  # type: ignore[assignment]
    glob_module.glob = _GUARD_ORIGINALS["glob.glob"]  # type: ignore[assignment]
    glob_module.iglob = _GUARD_ORIGINALS["glob.iglob"]  # type: ignore[assignment]
    sqlite3.connect = _GUARD_ORIGINALS["sqlite3.connect"]  # type: ignore[assignment]

    from pathlib import Path as _Path

    for name in (
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "open",
        "iterdir",
        "glob",
        "rglob",
    ):
        key = f"Path.{name}"
        if key in _GUARD_ORIGINALS:
            setattr(_Path, name, _GUARD_ORIGINALS[key])

    _GUARD_ORIGINALS.clear()
    _ACTIVE = False
    _ALLOWED_READ = ()
    _ALLOWED_WRITE = ()


def activate_python_guards(
    session_root: Path,
    *,
    venv_dir: Optional[Path] = None,
    extra_read: Optional[Sequence[Path]] = None,
) -> None:
    """Install Python-level FS guards (macOS / Landlock fallback)."""
    global _ACTIVE, _ALLOWED_READ, _ALLOWED_WRITE

    if not confinement_enabled():
        return

    session_root = session_root.resolve()
    read_paths, write_paths = collect_confinement_paths(
        session_root,
        venv_dir=venv_dir,
        extra_read=extra_read,
    )
    _ALLOWED_READ = tuple(read_paths)
    _ALLOWED_WRITE = tuple(write_paths)
    _ACTIVE = True
    if not _GUARD_ORIGINALS:
        _install_python_guards()


def activate_confinement(
    session_root: Path,
    *,
    venv_dir: Optional[Path] = None,
    extra_read: Optional[Sequence[Path]] = None,
) -> None:
    """Landlock + Python guards in the current process (legacy / in-process use)."""
    if not confinement_enabled():
        return
    read_paths, write_paths = collect_confinement_paths(
        session_root,
        venv_dir=venv_dir,
        extra_read=extra_read,
    )
    apply_landlock(read_paths, write_paths)
    activate_python_guards(session_root, venv_dir=venv_dir, extra_read=extra_read)


def extract_python_script_argv(argv: Sequence[str]) -> list[str]:
    """
    Normalize ``[python, -u, script.py, ...]`` → ``[script.py, ...]``.

    ``runpy.run_path`` must never receive the interpreter binary as the script path.
    """
    parts = list(argv)
    if not parts:
        return parts

    if len(parts) >= 2:
        name = Path(parts[0]).name.lower()
        if name.startswith("python") or name in ("uv",):
            idx = 1
            while (
                idx < len(parts)
                and parts[idx].startswith("-")
                and not parts[idx].endswith(".py")
            ):
                idx += 1
            if idx < len(parts):
                return parts[idx:]

    if parts[0].endswith(".py"):
        return parts

    for i, token in enumerate(parts):
        if str(token).endswith(".py"):
            return parts[i:]
    return parts


def wrap_confined_argv(
    wrapper_python: Path,
    argv: Sequence[str],
    *,
    mode: str,
) -> list[str]:
    """
    Wrap ``argv`` with ``python -m src.security.sandbox_subprocess_entry``.

    ``mode`` is ``python`` (runpy user script) or ``exec`` (landlock + execvp).
    """
    base = [
        str(wrapper_python),
        "-u",
        "-m",
        "src.security.sandbox_subprocess_entry",
    ]
    if mode == "python":
        script_argv = extract_python_script_argv(argv)
        if not script_argv:
            raise ValueError("python confinement mode requires a .py script in argv")
        return [*base, "--python", *script_argv]
    return [*base, "--", *argv]


def sandbox_runner_argv(python_exe: str, script_path: Path) -> list[str]:
    """Backward-compatible argv for confined Python scripts."""
    return wrap_confined_argv(
        Path(python_exe),
        [str(script_path)],
        mode="python",
    )

"""
Esecuzione Python limitata alla cartella della sessione (read uploads/derived, write workspace/).
Il codice viene salvato come file .py sotto workspace/ prima dell'esecuzione (traceback e debug),
con verifica sintattica obbligatoria e controllo opzionale ruff se installato.
"""
from __future__ import annotations

import builtins
import io
import os
import shutil
import subprocess
import sys
import json
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional, Tuple, Union

from ..security.session_env import build_session_env
from ..security.session_runner import run_session_subprocess
from ..session_workspace import ensure_session_dirs, safe_resolve, session_root
from .session_venv import resolve_run_python_executable, session_venv_dir

# Script salvato su disco prima di ogni esecuzione (path relativo alla sessione).
_SANDBOX_ENTRY_PY = "workspace/_sandbox_last_run.py"


def _format_syntax_error(exc: SyntaxError, source: str) -> str:
    """Messaggio leggibile per errori di sintassi (es. parentesi non chiuse)."""
    lines = source.splitlines()
    loc = getattr(exc, "lineno", None) or 1
    out = [
        f"SyntaxError: {exc.msg}",
        f"  (linea {loc}, file {_SANDBOX_ENTRY_PY})",
    ]
    if 1 <= loc <= len(lines):
        line_txt = lines[loc - 1]
        out.append(f"  {line_txt}")
        off = getattr(exc, "offset", None)
        if off and isinstance(off, int) and off > 0:
            out.append(f"  {' ' * (off - 1)}^")
    return "\n".join(out)


def _ruff_subprocess_env() -> dict[str, str]:
    """Writable cache dir for ruff (sandbox containers use read-only /app)."""
    env = os.environ.copy()
    cache = (env.get("RUFF_CACHE_DIR") or "").strip()
    if not cache:
        cache = "/tmp/ruff_cache"
    env["RUFF_CACHE_DIR"] = cache
    try:
        Path(cache).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return env


def _ruff_check_optional(path: Path) -> Tuple[bool, str]:
    """
    Se `ruff` è sul PATH, esegue un controllo statico sul file.
    Con AION_SANDBOX_RUFF_BLOCK=1 un exit code != 0 blocca l'esecuzione.
    Altrimenti gli avvisi vengono solo allegati in coda all'output in caso di successo.
    """
    ruff = shutil.which("ruff")
    if not ruff:
        return True, ""
    try:
        proc = subprocess.run(
            [ruff, "check", str(path), "--output-format", "concise"],
            capture_output=True,
            text=True,
            timeout=120,
            env=_ruff_subprocess_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return True, f"\n[ruff non eseguito: {e}]\n"
    combined = ((proc.stdout or "").strip() + "\n" + (proc.stderr or "").strip()).strip()
    if proc.returncode == 0:
        return True, ""
    low = combined.lower()
    if "failed to initialize cache" in low or "read-only file system" in low:
        return True, ""
    block = os.environ.get("AION_SANDBOX_RUFF_BLOCK", "0").lower() in (
        "1",
        "true",
        "yes",
    )
    if block:
        return (
            False,
            "Ruff ha segnalato problemi (esecuzione bloccata; imposta AION_SANDBOX_RUFF_BLOCK=0 per ignorare):\n"
            + (combined or "(nessun dettaglio)"),
        )
    return True, f"\n[Avviso ruff (non bloccante)]\n{combined}\n"

# SANDBOX NETWORK EGRESS:
# execute() blocca filesystem traversal ma NON il network (per design del modo exec interno).
# Per script che richiedono HTTP, usare sandbox_run_python_file / subprocess o impostare
# AION_SANDBOX_ALLOW_HTTP_IMPORTS=1 per consentire import requests/httpx (non raccomandato).

_HTTP_IN_SANDBOX = os.getenv("AION_SANDBOX_ALLOW_HTTP_IMPORTS", "0").lower() in ("1", "true", "yes")

# Moduli consentiti per `import ...` / `from ... import` (solo primo segmento del nome modulo).
# Esclusi: subprocess, socket, multiprocessing, ctypes, pickle (unsafe), pathlib (path arbitrari).
_SANDBOX_IMPORT_CORE: FrozenSet[str] = frozenset(
    {
        # --- Libreria standard (dati / testo / numerici) ---
        "array",
        "base64",
        "binascii",
        "bisect",
        "calendar",
        "codecs",
        "collections",
        "contextlib",
        "copy",
        "csv",
        "dataclasses",
        "datetime",
        "decimal",
        "difflib",
        "enum",
        "fractions",
        "functools",
        "graphlib",
        "hashlib",
        "heapq",
        "io",
        "itertools",
        "json",
        "logging",
        "math",
        "numbers",
        "operator",
        "pprint",
        "random",
        "re",
        "secrets",
        "statistics",
        "string",
        "textwrap",
        "types",
        "typing",
        "unicodedata",
        "uuid",
        "zlib",
        # --- Terze parti (già in requirements / usi tipici agente) ---
        "dateutil",
        "numpy",
        "pandas",
        "openpyxl",
        "pypdf",
        "pdfplumber",
        "pdf2image",
        "fitz",
        "docx",
        "PIL",
        "tabulate",
    }
)

_SANDBOX_IMPORT_WHITELIST: FrozenSet[str] = _SANDBOX_IMPORT_CORE | (
    frozenset({"requests", "httpx"}) if _HTTP_IN_SANDBOX else frozenset()
)


def _sandbox_safe_import(name: str, globals=None, locals=None, fromlist=(), level=0):
    base = (name or "").strip().split(".", 1)[0]
    if not base or base not in _SANDBOX_IMPORT_WHITELIST:
        sample = ", ".join(sorted(_SANDBOX_IMPORT_WHITELIST)[:24])
        raise ImportError(
            f"import '{name}' not allowed nella sandbox. "
            f"Allowed examples: {sample}, ... "
            f"(oppure usa pd/np/json/re già pre-caricati)."
        )
    return builtins.__import__(name, globals, locals, fromlist, level)


class SessionSandboxExecutor:
    """exec() con builtins ristretti e accesso file solo sotto session root."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        ensure_session_dirs(session_id)
        self._root = session_root(session_id)

    def _read_file(self, relative_path: str, max_bytes: int = 2_000_000) -> str:
        p = safe_resolve(self.session_id, relative_path, must_exist=True)
        if p.stat().st_size > max_bytes:
            raise ValueError(f"file too large (max {max_bytes} bytes)")
        return p.read_text(encoding="utf-8", errors="replace")

    def _write_workspace(self, relative_path: str, content: str) -> str:
        rel = relative_path.strip().replace("\\", "/").lstrip("/")
        if not rel.startswith("workspace/"):
            raise ValueError("writing allowed only under workspace/")
        p = safe_resolve(self.session_id, rel, must_exist=False)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return rel

    def _list_files(self, subdir: str = "uploads") -> str:
        from ..session_workspace import list_dir

        rows = list_dir(self.session_id, subdir=subdir)
        return json.dumps(rows, ensure_ascii=False, indent=2)

    def _sandbox_open(
        self,
        file: Union[str, bytes, os.PathLike[str]],
        mode: str = "r",
        buffering: int = -1,
        encoding: Optional[str] = None,
        errors: Optional[str] = None,
        newline: Optional[str] = None,
        closefd: bool = True,
        opener: Any = None,
    ):
        """
        open() limitato alla root sessione: lettura ovunque (uploads/workspace/derived),
        scrittura solo sotto workspace/ e derived/.
        """
        if opener is not None:
            raise TypeError("opener non supportato nella sandbox")
        if isinstance(file, int):
            raise TypeError("file descriptor intero non supportato")

        raw = os.fsdecode(file) if isinstance(file, bytes) else os.fspath(file)
        raw = raw.replace("\\", "/").strip()
        if not raw or ".." in raw or raw.startswith("/"):
            raise ValueError("use a session-relative path, es. workspace/out.csv")
        rel = raw.lstrip("/")
        top = rel.split("/", 1)[0] if "/" in rel else rel

        mode_l = mode or "r"
        can_write = any(c in mode_l for c in ("w", "a", "x", "+")) or "r+" in mode_l
        if can_write:
            if top not in ("workspace", "derived"):
                raise ValueError("writing allowed only under workspace/ o derived/")
        if top == "uploads" and can_write:
            raise ValueError("uploads/ is read-only; use workspace/")

        full: Path = safe_resolve(self.session_id, rel, must_exist=False)
        if can_write:
            full.parent.mkdir(parents=True, exist_ok=True)
        return builtins.open(
            full, mode, buffering, encoding, errors, newline, closefd
        )

    def execute(self, code: str, *, require_result: bool = True) -> str:
        safe_builtins = {
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "len": len,
            "range": range,
            "enumerate": enumerate,
            "zip": zip,
            "int": int,
            "float": float,
            "str": str,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "sorted": sorted,
            "reversed": reversed,
            "print": print,
            "open": self._sandbox_open,
            "__import__": _sandbox_safe_import,
        }

        import math
        import re as re_mod

        try:
            import numpy as np  # noqa: N816
        except ImportError:
            np = None  # type: ignore
        try:
            import pandas as pd  # noqa: N816
        except ImportError:
            pd = None  # type: ignore

        def read_file(rel: str, max_bytes: int = 2_000_000) -> str:
            return self._read_file(rel, max_bytes=max_bytes)

        def write_workspace(rel: str, content: str) -> str:
            return self._write_workspace(rel, content)

        def list_files(subdir: str = "uploads") -> str:
            return self._list_files(subdir=subdir)

        safe_globals: Dict[str, Any] = {
            "__builtins__": safe_builtins,
            "math": math,
            "re": re_mod,
            "json": json,
            "SESSION_ROOT": str(self._root),
            "read_file": read_file,
            "write_workspace": write_workspace,
            "list_files": list_files,
        }
        if np is not None:
            safe_globals["np"] = np
        if pd is not None:
            safe_globals["pd"] = pd

        code = (code or "").replace("\r\n", "\n")
        if not code.strip():
            return "Error: empty Python code."

        # 1) Salva sempre come file .py (newline preservati; traceback con nome file reale)
        try:
            entry_path = safe_resolve(self.session_id, _SANDBOX_ENTRY_PY, must_exist=False)
        except (OSError, ValueError) as e:
            return f"Error: unable to resolve script path: {e}"
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        entry_path.write_text(code, encoding="utf-8")

        # 2) Verifica sintassi prima di exec (evita errori opachi su "una riga")
        try:
            code_obj = compile(code, str(entry_path), "exec")
        except SyntaxError as e:
            return f"Error: {_format_syntax_error(e, code)}"

        # 3) Lint opzionale (ruff), bloccante solo se richiesto
        ok_ruff, ruff_note = _ruff_check_optional(entry_path)
        if not ok_ruff:
            return f"Error: {ruff_note}"

        local_vars: Dict[str, Any] = {}
        old_stdout = sys.stdout
        redirected = io.StringIO()
        sys.stdout = redirected
        old_cwd = os.getcwd()
        try:
            # Path relativi tipo workspace/foo.xlsx risolvono sotto data/sessions/<id>/
            os.chdir(self._root)
            exec(code_obj, safe_globals, local_vars)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
        finally:
            sys.stdout = old_stdout
            try:
                os.chdir(old_cwd)
            except OSError:
                pass

        if "result" not in local_vars:
            if not require_result:
                out = redirected.getvalue()
                return f"Execution successful.\nStdout:\n{out}" if out else "Execution successful. (no output)"
            return (
                "Error: assegna l'output finale alla variabile 'result'.\n"
                "Stdout:\n"
                + redirected.getvalue()
                + "\nHint: for libraries not on the whitelist (es. docx, reportlab) usa "
                "il formato `<aion_artifact>` per generare il file .py, poi eseguilo con `sandbox_run_python_file`."
            )
        out = redirected.getvalue()
        res = local_vars["result"]
        msg = "Execution successful.\n"
        msg += f"(Script salvato in {_SANDBOX_ENTRY_PY})\n"
        if out:
            msg += f"Stdout:\n{out}\n"
        msg += f"Result: {res!r}"
        if ruff_note:
            msg += ruff_note
        return msg

    def run_file(self, relative_path: str, extra_args: Optional[list] = None) -> str:
        """
        Esegue ``python -u <script>`` con cwd nella root sessione (come da terminale).
        Consente qualsiasi import installato nell'ambiente del processo MCP (docx, reportlab, …).
        """
        extra_args = list(extra_args or [])
        rel = relative_path.strip().replace("\\", "/").lstrip("/")
        if not rel.startswith("workspace/"):
            return (
                "Error: only run scripts under workspace/, es. workspace/convert.py "
                "(prima emetti il codice usando `<aion_artifact>` nel testo)."
            )
        if not rel.lower().endswith(".py"):
            if rel.lower().endswith((".js", ".mjs", ".cjs")):
                return (
                    "Error: per script JavaScript usa sandbox_run_node_file "
                    f"(es. sandbox_run_node_file(relative_path=\"{rel}\"))."
                )
            return "Error: path must end with .py (or use sandbox_run_node_file for .js)"
        try:
            entry_path = safe_resolve(self.session_id, rel, must_exist=True)
        except Exception as e:
            return f"Error: path invalid: {e}"
        if not entry_path.is_file():
            return "Error: file not found."

        try:
            src = entry_path.read_text(encoding="utf-8", errors="replace")
            compile(src, str(entry_path), "exec")
        except SyntaxError as e:
            return f"Error: {_format_syntax_error(e, src)}"

        ok_ruff, ruff_note = _ruff_check_optional(entry_path)
        if not ok_ruff:
            return f"Error: {ruff_note}"

        timeout = float(os.environ.get("AION_SANDBOX_RUN_TIMEOUT_SEC", "600"))
        max_out = int(os.environ.get("AION_SANDBOX_MAX_OUTPUT_BYTES", "500000") or "500000")
        py_exe = resolve_run_python_executable(self.session_id)
        cmd = [str(py_exe), "-u", str(entry_path)] + extra_args
        venv = session_venv_dir(self.session_id) if session_venv_dir(self.session_id).is_dir() else None
        env = build_session_env(
            self.session_id,
            session_root=self._root,
            venv_dir=venv,
        )
        try:
            proc = run_session_subprocess(
                self.session_id,
                cmd,
                cwd=str(self._root),
                env=env,
                timeout=timeout,
                confinement_root=self._root,
                confinement_venv=venv,
                confinement_mode="python",
                confinement_executables=[Path(py_exe)],
            )
        except subprocess.TimeoutExpired:
            return f"Error: timeout dopo {timeout:g}s (AION_SANDBOX_RUN_TIMEOUT_SEC)."
        parts: list[str] = [f"Exit code: {proc.returncode}", f"Command: {' '.join(cmd)}"]
        if proc.stdout:
            parts.append("--- stdout ---\n" + proc.stdout)
        if proc.stderr:
            parts.append("--- stderr ---\n" + proc.stderr)
        combined = "\n".join(parts)
        raw = combined.encode("utf-8", errors="replace")
        if len(raw) > max_out:
            combined = raw[:max_out].decode("utf-8", errors="replace") + "\n...[output truncated]\n"
        if ruff_note:
            combined += ruff_note
        if proc.returncode != 0:
            return f"Error:\n{combined}"
        return f"OK\n{combined}"

    def run_node_file(self, relative_path: str, extra_args: Optional[list] = None) -> str:
        """Esegue ``node <script>`` con cwd nella root sessione (docx-js, ecc.)."""
        import shutil

        extra_args = list(extra_args or [])
        rel = relative_path.strip().replace("\\", "/").lstrip("/")
        if not rel.startswith("workspace/"):
            return (
                "Error: only run scripts under workspace/, es. workspace/create_doc.js"
            )
        if not rel.lower().endswith((".js", ".mjs", ".cjs")):
            if rel.lower().endswith(".py"):
                return (
                    "Error: per script Python usa sandbox_run_python_file "
                    f"(es. sandbox_run_python_file(relative_path=\"{rel}\"))."
                )
            return "Error: il path deve terminare con .js, .mjs o .cjs"

        try:
            entry_path = safe_resolve(self.session_id, rel, must_exist=True)
        except Exception as e:
            return f"Error: path invalid: {e}"
        if not entry_path.is_file():
            return "Error: file not found."

        node_exe = (os.environ.get("AION_NODE_PATH") or "").strip() or shutil.which("node")
        if not node_exe:
            return (
                "Error: Node.js not found sul server. Installa Node o imposta AION_NODE_PATH. "
                "Alternativa: genera il .docx con python-docx via sandbox_run_python_file."
            )

        timeout = float(os.environ.get("AION_SANDBOX_RUN_TIMEOUT_SEC", "600"))
        max_out = int(os.environ.get("AION_SANDBOX_MAX_OUTPUT_BYTES", "500000") or "500000")
        node_path = Path(node_exe)
        cmd = [str(node_path), str(entry_path)] + extra_args
        env = build_session_env(self.session_id, session_root=self._root)
        try:
            proc = run_session_subprocess(
                self.session_id,
                cmd,
                cwd=str(self._root),
                env=env,
                timeout=timeout,
                confinement_root=self._root,
                confinement_mode="exec",
                confinement_executables=[node_path],
            )
        except subprocess.TimeoutExpired:
            return f"Error: timeout dopo {timeout:g}s (AION_SANDBOX_RUN_TIMEOUT_SEC)."
        parts: list[str] = [f"Exit code: {proc.returncode}", f"Command: {' '.join(cmd)}"]
        if proc.stdout:
            parts.append("--- stdout ---\n" + proc.stdout)
        if proc.stderr:
            parts.append("--- stderr ---\n" + proc.stderr)
        combined = "\n".join(parts)
        raw = combined.encode("utf-8", errors="replace")
        if len(raw) > max_out:
            combined = raw[:max_out].decode("utf-8", errors="replace") + "\n...[output truncated]\n"
        if proc.returncode != 0:
            hint = ""
            if "cannot find module" in combined.lower() or "module not found" in combined.lower():
                hint = (
                    "\nHINT: install deps with sandbox_install_npm_packages(packages=[\"docx\"]), "
                    "then sandbox_run_node_file again. Do not use sandbox_exec_allowlisted for Node. "
                    "Alternative: python-docx via sandbox_install_python_packages + sandbox_run_python_file."
                )
            return f"Error:\n{combined}{hint}"
        return f"OK\n{combined}"

"""Shared uv-based venv + requirements install (used by setup/upgrade scripts)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"
REQ = ROOT / "requirements.txt"


def uv_available() -> bool:
    return shutil.which("uv") is not None


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def ensure_venv(base_python: str, *, dry_run: bool = False) -> str:
    """Create .venv and install requirements.txt using uv when available, else pip."""
    if dry_run:
        return str(venv_python() if venv_python().exists() else Path(base_python))

    py = venv_python()
    if uv_available():
        if not py.exists():
            rc = subprocess.run(["uv", "venv", str(VENV_DIR)], cwd=str(ROOT)).returncode
            if rc != 0:
                raise SystemExit(rc)
        if REQ.exists():
            env = {**os.environ, "VIRTUAL_ENV": str(VENV_DIR)}
            rc = subprocess.run(
                ["uv", "pip", "install", "-r", str(REQ)],
                cwd=str(ROOT),
                env=env,
            ).returncode
            if rc != 0:
                raise SystemExit(rc)
        return str(py)

    if not py.exists():
        rc = subprocess.run(
            [base_python, "-m", "venv", str(VENV_DIR)], cwd=str(ROOT)
        ).returncode
        if rc != 0:
            raise SystemExit(rc)
    py_exec = str(py)
    for cmd in (
        [py_exec, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
        [py_exec, "-m", "pip", "install", "-r", str(REQ)],
    ):
        if cmd[-1] == str(REQ) and not REQ.exists():
            continue
        rc = subprocess.run(cmd, cwd=str(ROOT)).returncode
        if rc != 0:
            raise SystemExit(rc)
    return py_exec


def main() -> int:
    base = sys.executable or "python3"
    ensure_venv(base, dry_run=False)
    print(f"OK: runtime ready at {venv_python()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

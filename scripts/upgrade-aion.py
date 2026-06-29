#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    core_script = root / "scripts" / "upgrade_core.py"
    if not core_script.is_file():
        print(f"Missing script: {core_script}", file=sys.stderr)
        return 2

    ap = argparse.ArgumentParser(description="Python wrapper for scripts/upgrade_core.py")
    ap.add_argument("args", nargs=argparse.REMAINDER, help="Pass-through args")
    ns = ap.parse_args()

    forwarded = list(ns.args)
    if "--dry-run" not in forwarded and "--prepare-runtime" not in forwarded:
        forwarded.append("--prepare-runtime")
    cmd = [sys.executable, str(core_script), *forwarded]
    proc = subprocess.run(cmd, cwd=str(root))
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())

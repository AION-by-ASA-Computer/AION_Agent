#!/usr/bin/env python3
"""Fail if runtime files under data/ are tracked by git (except whitelist)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Paths allowed to remain in git (test fixtures, sample plugins).
ALLOWED_PREFIXES = (
    "data/eval_datasets/",
    "data/plugins/",
)


def _tracked_data_files() -> list[str]:
    r = subprocess.run(
        ["git", "ls-files", "data/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return []
    out: list[str] = []
    for line in r.stdout.splitlines():
        p = line.strip()
        if not p:
            continue
        if any(p.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            continue
        out.append(p)
    return out


def main() -> int:
    bad = _tracked_data_files()
    if not bad:
        print("OK: no disallowed tracked files under data/")
        return 0
    print(
        "ERROR: runtime data must not be tracked in git (whitelist: eval_datasets, plugins):"
    )
    for p in bad:
        print(f"  - {p}")
    print("\nFix: git rm --cached <path>  and ensure .gitignore covers data/*")
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Wrapper so check_data_git_tracking is discoverable by pytest in CI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_disallowed_data_tracked() -> None:
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_data_git_tracking.py")],
        cwd=REPO_ROOT,
        check=False,
    )
    assert r.returncode == 0, "Runtime data/ must not be tracked in git"

#!/usr/bin/env python3
"""Reconcile data/runtime.env with repo .env (sparse admin overrides)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.runtime.env_sync import (  # noqa: E402
    apply_merged_env_to_os,
    reconcile_runtime_env,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync data/runtime.env with .env (keep only admin overrides)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show reconcile report without writing files",
    )
    parser.add_argument(
        "--apply-process",
        action="store_true",
        help="Also load merged env into the current process",
    )
    args = parser.parse_args()

    report = reconcile_runtime_env(dry_run=args.dry_run)
    print(json.dumps(report, indent=2))

    if args.apply_process and not args.dry_run:
        apply_merged_env_to_os()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

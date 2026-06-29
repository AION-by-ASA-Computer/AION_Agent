#!/usr/bin/env python3
"""Backfill messages.timeline_json for existing assistant messages (idempotent)."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import src.aion_env  # noqa: F401, E402

from src.runtime.timeline_backfill import backfill_message_timelines  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill message timelines")
    parser.add_argument("--dry-run", action="store_true", help="Count only, do not write")
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()
    if not os.getenv("AION_DB_URL"):
        print("AION_DB_URL not set", file=sys.stderr)
        sys.exit(1)
    n = asyncio.run(
        backfill_message_timelines(batch_size=args.batch_size, dry_run=args.dry_run)
    )
    print(f"{'Would update' if args.dry_run else 'Updated'} {n} assistant message(s)")


if __name__ == "__main__":
    main()

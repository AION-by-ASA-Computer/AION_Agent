#!/usr/bin/env python3
"""Upload local session files to configured StorageBackend (see plan §5.2)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.storage import get_storage_backend


def main(dry_run: bool) -> None:
    root = Path(os.getenv("AION_STORAGE_LOCAL_ROOT", "data")) / "sessions"
    be = get_storage_backend()
    n = 0
    for fp in root.glob("*/uploads/*"):
        if not fp.is_file():
            continue
        cid = fp.parent.parent.name
        key = f"{os.getenv('AION_DEFAULT_TENANT_ID', 'default')}/conversations/{cid}/uploads/{fp.name}"
        if dry_run:
            print("would upload", key)
            continue
        be.put_bytes(key, fp.read_bytes(), "application/octet-stream")
        n += 1
    print("uploaded" if not dry_run else "dry-run", n)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    main(args.dry_run)

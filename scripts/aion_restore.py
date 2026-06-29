#!/usr/bin/env python3
"""Restore from aion_backup_*.tar.gz (dry-run lists members)."""
from __future__ import annotations

import argparse
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(archive: Path, dry_run: bool) -> None:
    with tarfile.open(archive, "r:gz") as tf:
        for m in tf.getmembers():
            print(m.name)
            if dry_run:
                continue
            tf.extract(m, path=ROOT)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("archive", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    main(args.archive, args.dry_run)

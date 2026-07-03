#!/usr/bin/env python3
"""
Merge skill packages from local config/skills/ into config_std/skills/ (maintainer / dev).

Copies directories that contain SKILL.md (or skill.md). Does not delete extras in
config_std. Flat .md skills in config/ are copied if missing in config_std/.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _is_skill_package_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    return (path / "SKILL.md").is_file() or (path / "skill.md").is_file()


def sync_packages(
    src_root: Path,
    dst_root: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    if not src_root.is_dir():
        print(f"[skip] {src_root} not found")
        return 0
    dst_root.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0
    for entry in sorted(src_root.iterdir()):
        if not _is_skill_package_dir(entry):
            continue
        dest = dst_root / entry.name
        if dest.is_dir() and not force and _is_skill_package_dir(dest):
            skipped += 1
            continue
        if dry_run:
            print(f"[dry-run] would copy package {entry.name}")
            copied += 1
            continue
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(entry, dest)
        print(f"[copy] package {entry.name} -> config_std/skills/")
        copied += 1

    for md in sorted(src_root.glob("*.md")):
        dest = dst_root / md.name
        if dest.is_file() and not force:
            skipped += 1
            continue
        if dry_run:
            print(f"[dry-run] would copy {md.name}")
            copied += 1
            continue
        shutil.copy2(md, dest)
        print(f"[copy] {md.name} -> config_std/skills/")
        copied += 1

    print(f"Done. packages/md copied={copied} skipped={skipped}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Merge config/skills packages into config_std/skills"
    )
    ap.add_argument(
        "--force", action="store_true", help="Overwrite existing packages in config_std"
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    root = _root()
    return sync_packages(
        root / "config" / "skills",
        root / "config_std" / "skills",
        force=args.force,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())

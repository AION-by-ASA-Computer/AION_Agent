#!/usr/bin/env python3
"""
Sposta i pacchetti skill proprietari da config_std/skills/ a config_proprietary/skills/.

Esegui una tantum sul maintainer machine prima di committare la rimozione da config_std.
Con --remove-from-std elimina le directory da config_std dopo la copia.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STD_SKILLS = ROOT / "config_std" / "skills"
PROP_SKILLS = ROOT / "config_proprietary" / "skills"
MANIFEST = ROOT / "config_proprietary" / "manifest.yaml"


def _load_slugs() -> list[str]:
    if not MANIFEST.is_file():
        return ["docx", "pdf", "pptx", "xlsx"]
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {}
        return [str(s).strip() for s in (data.get("skills") or []) if str(s).strip()]
    except Exception:
        return ["docx", "pdf", "pptx", "xlsx"]


def migrate(*, remove_from_std: bool = False, purge_std: bool = False, dry_run: bool = False) -> int:
    slugs = _load_slugs()
    if not STD_SKILLS.is_dir():
        print(f"ERRORE: {STD_SKILLS} non trovata.", file=sys.stderr)
        return 1

    if not PROP_SKILLS.exists() and not dry_run:
        PROP_SKILLS.mkdir(parents=True, exist_ok=True)

    moved = 0
    purged = 0
    for slug in slugs:
        src = STD_SKILLS / slug
        dst = PROP_SKILLS / slug
        if src.is_dir():
            if dst.exists():
                print(f"  [skip-copy] config_proprietary/skills/{slug}/ già presente")
            else:
                print(f"  [move] {src.relative_to(ROOT)} → {dst.relative_to(ROOT)}")
                if not dry_run:
                    shutil.copytree(src, dst)
                moved += 1
            if remove_from_std or purge_std:
                print(f"  [rm]   config_std/skills/{slug}/")
                if not dry_run:
                    shutil.rmtree(src)
                purged += 1
        elif purge_std:
            print(f"  [ok]   config_std/skills/{slug}/ assente")

    if moved == 0 and purged == 0:
        print("Nessun pacchetto da migrare o rimuovere.")
    else:
        if moved:
            print(f"\nMigrati {moved} pacchetti in config_proprietary/skills/.")
        if purged:
            print(f"Rimossi {purged} pacchetti da config_std/skills/.")
        print("Esegui: python scripts/sync_proprietary_config.py --force")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Copia skill proprietarie da config_std a config_proprietary"
    )
    ap.add_argument(
        "--remove-from-std",
        action="store_true",
        help="Rimuove le directory da config_std/skills/ dopo la copia.",
    )
    ap.add_argument(
        "--purge-std",
        action="store_true",
        help="Rimuove da config_std anche se config_proprietary ha già il pacchetto.",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    return migrate(
        remove_from_std=args.remove_from_std,
        purge_std=args.purge_std,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())

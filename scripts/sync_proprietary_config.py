#!/usr/bin/env python3
"""
Sync proprietary skill packages from config_proprietary/skills/ → config/skills/.

Same semantics as sync_config.py --skills-only: safe by default, --force overwrites.
Only runs when config_proprietary/skills/ exists (local, gitignored content).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_SKIP_DIR_NAMES = frozenset({".git", "__pycache__", ".pytest_cache", "node_modules"})


def _should_skip(rel: Path) -> bool:
    return any(part in _SKIP_DIR_NAMES for part in rel.parts)


def load_manifest_skills(root: Path) -> list[str]:
    manifest = root / "config_proprietary" / "manifest.yaml"
    if not manifest.is_file():
        return ["docx", "pdf", "pptx", "xlsx"]
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        skills = data.get("skills") or []
        return [str(s).strip() for s in skills if str(s).strip()]
    except Exception:
        return ["docx", "pdf", "pptx", "xlsx"]


def sync_proprietary_config(
    force: bool = False,
    *,
    root: Path | None = None,
    dry_run: bool = False,
) -> int:
    script_dir = Path(__file__).parent.absolute()
    root = root or script_dir.parent
    src_root = root / "config_proprietary" / "skills"
    dst_root = root / "config" / "skills"

    if not src_root.is_dir():
        print(
            "config_proprietary/skills/ assente — skip sync proprietario "
            "(vedi config_proprietary/README.md)."
        )
        return 0

    expected = load_manifest_skills(root)
    present = sorted(
        p.name for p in src_root.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    missing = [s for s in expected if not (src_root / s).is_dir()]
    if missing:
        print(f"[warn] Pacchetti manifest ma assenti in config_proprietary/skills/: {missing}")

    print("\n🔒  AION Sync Proprietary Skills\n")
    print(f"    source : {src_root}")
    print(f"    target : {dst_root}")
    print(f"    mode   : {'FORCE' if force else 'safe (skip existing)'}")
    print(f"    packages present: {present or '(none)'}\n")

    # Legacy duplicate layout: config/skills/<slug>/<slug>/ from old sync — remove stale tree.
    if not dry_run:
        for slug in expected:
            nested = dst_root / slug / slug
            if nested.is_dir():
                print(f"  [CLEAN]     skills/{slug}/{slug}/ (legacy duplicate)")
                shutil.rmtree(nested)

    if not dst_root.exists():
        if dry_run:
            print(f"[dry-run] mkdir {dst_root}")
        else:
            dst_root.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0
    overwritten = 0

    for item in src_root.rglob("*"):
        rel = item.relative_to(src_root)
        if _should_skip(rel):
            continue
        target = dst_root / rel
        if item.is_dir():
            if not dry_run and not target.exists():
                target.mkdir(parents=True, exist_ok=True)
            continue
        if not target.exists():
            print(f"  [COPY]      skills/{rel}")
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
            copied += 1
        elif force:
            print(f"  [OVERWRITE] skills/{rel}")
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
            overwritten += 1
        else:
            skipped += 1

    print(
        f"\nSync proprietario completato. "
        f"Copiati: {copied}  Sovrascritti: {overwritten}  Saltati: {skipped}\n"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Sincronizza config_proprietary/skills/ → config/skills/"
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Sovrascrive i file esistenti in config/skills/.",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    return sync_proprietary_config(force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

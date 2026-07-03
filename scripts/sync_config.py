#!/usr/bin/env python3
"""
Sincronizza la directory 'config/' (locale, ignorata da git) partendo dai template in 'config_std/'.
Inizializza i file mancanti senza sovrascrivere quelli esistenti.
Con --force sovrascrive anche i file esistenti (utile per propagare aggiornamenti da config_std/).
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.runtime.profile_sync_state import (  # noqa: E402
    load_profile_sync_state,
    profile_rel_key,
    record_profile_after_sync,
    save_profile_sync_state,
    should_preserve_profile_on_force,
)

_SKIP_DIR_NAMES = frozenset({".git", "__pycache__", ".pytest_cache", "node_modules"})

# Never overwritten by ``--force`` (local deployment / MCP overlays / secrets).
_NEVER_FORCE_OVERWRITE = frozenset(
    {
        "mcp_registry.yaml",
        "mcp_registry.local.yaml",
        "mcp_registry.json",
        "mcp_registry.local.json",
        "mcp_connector_catalog.local.yaml",
    }
)


def _read_version(root: Path) -> str:
    """Legge la versione dal file centralizzato version.json nella root del repo."""
    try:
        return json.loads((root / "version.json").read_text(encoding="utf-8")).get(
            "version", "unknown"
        )
    except Exception:
        return "unknown"


def _should_skip(rel: Path) -> bool:
    return any(part in _SKIP_DIR_NAMES for part in rel.parts)


def sync_config(
    force: bool = False,
    *,
    skills_only: bool = False,
    profiles_only: bool = False,
    root: Path | None = None,
) -> None:
    script_dir = Path(__file__).parent.absolute()
    root = root or script_dir.parent
    src_dir = root / "config_std"
    dst_dir = root / "config"
    skills_src = src_dir / "skills"
    profiles_src = src_dir / "profiles"
    if profiles_only:
        scan_root = profiles_src
    elif skills_only:
        scan_root = skills_src
    else:
        scan_root = src_dir

    _ver = _read_version(root)
    print(f"\n🔄  AION Sync Config  —  {_ver}\n")
    print(f"    source : {scan_root}")
    print(f"    target : {dst_dir}")
    mode = "FORCE (overwrite existing)" if force else "safe (skip existing)"
    if skills_only:
        mode += " — skills/ only"
    if profiles_only:
        mode += " — profiles/ only"
    if _NEVER_FORCE_OVERWRITE and force:
        mode += f" (esclusi: {', '.join(sorted(_NEVER_FORCE_OVERWRITE))})"
    print(f"    mode   : {mode}\n")

    if not src_dir.exists():
        print(f"ERRORE: Directory sorgente {src_dir} non trovata.")
        sys.exit(1)

    if skills_only and not skills_src.is_dir():
        print(f"ERRORE: Directory sorgente {skills_src} non trovata.")
        sys.exit(1)
    if profiles_only and not profiles_src.is_dir():
        print(f"ERRORE: Directory sorgente {profiles_src} non trovata.")
        sys.exit(1)

    if not dst_dir.exists():
        print(f"Creazione directory config locale: {dst_dir}")
        dst_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0
    overwritten = 0
    profile_state = load_profile_sync_state(dst_dir)

    for item in scan_root.rglob("*"):
        rel_in_scan = item.relative_to(scan_root)
        if _should_skip(rel_in_scan):
            continue
        if profiles_only:
            rel_path = Path("profiles") / rel_in_scan
        elif skills_only:
            rel_path = Path("skills") / rel_in_scan
        else:
            rel_path = rel_in_scan
        target = dst_dir / rel_path

        if item.is_dir():
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
        else:
            if not target.exists():
                print(f"  [COPY]      {rel_path}")
                shutil.copy2(item, target)
                copied += 1
            elif force and rel_path.as_posix() in _NEVER_FORCE_OVERWRITE:
                skipped += 1
            elif force:
                rel_key = profile_rel_key(rel_path)
                if rel_key:
                    preserve, reason = should_preserve_profile_on_force(
                        target, item, profile_state, rel_key
                    )
                    if preserve:
                        print(f"  [SKIP]      {rel_path} ({reason})")
                        skipped += 1
                        continue
                print(f"  [OVERWRITE] {rel_path}")
                shutil.copy2(item, target)
                if rel_key:
                    record_profile_after_sync(target, profile_state, rel_key)
                overwritten += 1
            else:
                skipped += 1

    if profile_state:
        save_profile_sync_state(profile_state, dst_dir)

    # Placeholder per Skill Pubbliche (solo sync config completa)
    if not skills_only and not profiles_only:
        public_skills_cfg = dst_dir / "public_skills.yaml"
        if not public_skills_cfg.exists():
            with open(public_skills_cfg, "w", encoding="utf-8") as f:
                f.write("# Configurazione skill pubbliche\n")
                f.write("# Formato: \n")
                f.write("# skills:\n")
                f.write("#   - name: my_skill\n")
                f.write(
                    "#     url: https://github.com/user/skill-repo/raw/main/skill.md\n"
                )

    print(
        f"\nSincronizzazione completata. "
        f"Copiati: {copied}  Sovrascritti: {overwritten}  Saltati: {skipped}\n"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Sincronizza config_std/ -> config/ per AION Agent"
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Sovrascrive i file esistenti in config/ con i template aggiornati in config_std/.",
    )
    ap.add_argument(
        "--skills-only",
        action="store_true",
        help="Sincronizza solo config_std/skills/ → config/skills/ (utile dopo upgrade office).",
    )
    ap.add_argument(
        "--profiles-only",
        action="store_true",
        help="Sincronizza solo config_std/profiles/ → config/profiles/.",
    )
    args = ap.parse_args()
    if args.profiles_only and args.skills_only:
        ap.error("Usa solo uno tra --profiles-only e --skills-only")
    sync_config(
        force=args.force,
        skills_only=args.skills_only,
        profiles_only=args.profiles_only,
    )

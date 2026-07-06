#!/usr/bin/env python3
"""
Sincronizza la directory 'mcp_servers/' (locale, ignorata da git) partendo dai template in 'mcp_servers_std/'.
Inizializza i file mancanti senza sovrascrivere quelli esistenti.
Con --force sovrascrive anche i file esistenti (utile per propagare aggiornamenti da mcp_servers_std/).

Importante: il runtime avvia MCP da mcp_servers/ (es. skills_hub/server.py). Dopo modifiche a
mcp_servers_std/skills_hub (profile allowlist su skill_view), eseguire:

  python scripts/sync_mcp_servers.py --force

e riavviare il backend (ricicla pool stdio). Upgrade/setup chiamano sync con --force quando possibile.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

_SKIP_DIR_NAMES = frozenset({".git", "__pycache__", ".pytest_cache", "node_modules"})


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


def sync_mcp_servers(force: bool = False) -> None:
    script_dir = Path(__file__).parent.absolute()
    root = script_dir.parent
    src_dir = root / "mcp_servers_std"
    dst_dir = root / "mcp_servers"

    _ver = _read_version(root)
    print(f"\n🔄  AION Sync MCP Servers  —  {_ver}\n")
    print(f"    source : {src_dir}")
    print(f"    target : {dst_dir}")
    print(
        f"    mode   : {'FORCE (overwrite existing)' if force else 'safe (skip existing)'}\n"
    )

    if not src_dir.exists():
        print(f"ERRORE: Directory sorgente {src_dir} non trovata.")
        sys.exit(1)

    if not dst_dir.exists():
        print(f"Creazione directory mcp_servers locale: {dst_dir}")
        dst_dir.mkdir(parents=True, exist_ok=True)

    # Root __init__.py: rende ``mcp_servers`` importabile come package (admin_agent_db, seed, …).
    root_init_std = src_dir / "__init__.py"
    root_init_dst = dst_dir / "__init__.py"
    if root_init_std.is_file() and (force or not root_init_dst.is_file()):
        if not root_init_dst.is_file():
            print("  [COPY]      __init__.py")
        elif force:
            print("  [OVERWRITE] __init__.py")
        shutil.copy2(root_init_std, root_init_dst)

    copied = 0
    skipped = 0
    overwritten = 0

    for item in src_dir.rglob("*"):
        rel_path = item.relative_to(src_dir)
        if _should_skip(rel_path):
            continue
        target = dst_dir / rel_path

        if item.is_dir():
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
        else:
            if not target.exists():
                print(f"  [COPY]      {rel_path}")
                shutil.copy2(item, target)
                copied += 1
            elif force:
                print(f"  [OVERWRITE] {rel_path}")
                shutil.copy2(item, target)
                overwritten += 1
            else:
                skipped += 1

    print(
        f"\nSincronizzazione completata. "
        f"Copiati: {copied}  Sovrascritti: {overwritten}  Saltati: {skipped}\n"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Sincronizza mcp_servers_std/ -> mcp_servers/ per AION Agent"
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Sovrascrive i file esistenti in mcp_servers/ con i template/file aggiornati in mcp_servers_std/.",
    )
    args = ap.parse_args()
    sync_mcp_servers(force=args.force)

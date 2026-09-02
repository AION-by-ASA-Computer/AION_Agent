#!/usr/bin/env python3
"""
Merge missing MCP server entries from config_std/mcp_registry.yaml into config/mcp_registry.yaml.

config/mcp_registry.yaml is never force-overwritten by sync_config (local customizations).
This script adds only *new* server slugs from the std template so upgrades ship new builtins
(e.g. geocoding) without clobbering installed marketplace servers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.mcp_registry_io import load_registry_file  # noqa: E402

_SKIP_KEYS = frozenset({"_removed"})


def merge_mcp_registry_from_std(
    *,
    root: Path | None = None,
    dry_run: bool = False,
) -> list[str]:
    root = root or _REPO_ROOT
    std_path = root / "config_std" / "mcp_registry.yaml"
    dst_path = root / "config" / "mcp_registry.yaml"

    if not std_path.is_file():
        print(f"ERRORE: template non trovato: {std_path}")
        sys.exit(1)

    std = load_registry_file(str(std_path))
    if dst_path.is_file():
        local = load_registry_file(str(dst_path))
    else:
        local = {}
        if not dry_run:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            dst_path.write_text(
                "# Local MCP registry (merged from config_std on first run)\n",
                encoding="utf-8",
            )

    missing = [
        slug
        for slug in sorted(std.keys())
        if slug not in _SKIP_KEYS and slug not in local
    ]
    if not missing:
        print("MCP registry: nessuna voce mancante da config_std.")
        return []

    print(f"MCP registry: aggiungo {len(missing)} voce/i da config_std: {', '.join(missing)}")
    if dry_run:
        return missing

    blocks: list[str] = []
    for slug in missing:
        payload = {slug: std[slug]}
        block = yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).rstrip()
        blocks.append(block)

    separator = "\n\n" if dst_path.stat().st_size > 0 else ""
    with dst_path.open("a", encoding="utf-8") as fh:
        if separator:
            fh.write(separator)
        fh.write("\n\n".join(blocks))
        fh.write("\n")

    return missing


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra le voci che verrebbero aggiunte senza scrivere.",
    )
    args = ap.parse_args()
    merge_mcp_registry_from_std(dry_run=args.dry_run)


if __name__ == "__main__":
    main()

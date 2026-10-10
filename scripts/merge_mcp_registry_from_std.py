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

# Slugs removed from the product. Upgrade must delete them from local registries.
# Marketplace servers that are not in this set are left untouched.
RETIRED_MCP_SLUGS = frozenset(
    {"mempalace", "memory", "sql_query_memory", "sqlquerymemory"}
)


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
    retired = sorted(slug for slug in local if slug in RETIRED_MCP_SLUGS)
    skill_write_off = _disable_skill_write(local)
    for overlay in _overlay_paths(root):
        retired.extend(_strip_retired(overlay, dry_run=dry_run))
        if overlay.is_file() and not dry_run:
            overlay_data = load_registry_file(str(overlay))
            if _disable_skill_write(overlay_data):
                _write_registry(overlay, overlay_data)
                skill_write_off = True
        elif overlay.is_file() and dry_run:
            if _disable_skill_write(load_registry_file(str(overlay))):
                skill_write_off = True

    if not missing and not retired and not skill_write_off:
        print("MCP registry: nessuna voce mancante da config_std.")
        return []

    if missing:
        print(
            "MCP registry: aggiungo "
            f"{len(missing)} voce/i da config_std: {', '.join(missing)}"
        )
    if retired:
        print(f"MCP registry: rimuovo slug ritirati: {', '.join(retired)}")
    if skill_write_off:
        print("MCP registry: AION_SKILL_WRITE_ENABLED=0 su skills_hub.")
    if dry_run:
        return missing

    for slug in retired:
        local.pop(slug, None)
    for slug in missing:
        local[slug] = std[slug]
    _write_registry(dst_path, local)
    return missing


def _disable_skill_write(data: dict) -> bool:
    """Turn off the old skills_hub default that wrote curated skills during chat."""
    hub = data.get("skills_hub")
    if not isinstance(hub, dict):
        return False
    env = hub.get("env")
    if not isinstance(env, dict):
        return False
    current = str(env.get("AION_SKILL_WRITE_ENABLED", "0")).strip().lower()
    if current not in ("1", "true", "yes", "on"):
        return False
    env["AION_SKILL_WRITE_ENABLED"] = "0"
    return True


def _overlay_paths(root: Path) -> list[Path]:
    return [
        root / "config" / "mcp_registry.local.yaml",
        root / "data" / "mcp_registry.local.yaml",
    ]


def _strip_retired(path: Path, *, dry_run: bool) -> list[str]:
    if not path.is_file():
        return []
    data = load_registry_file(str(path))
    retired = sorted(slug for slug in data if slug in RETIRED_MCP_SLUGS)
    if not retired or dry_run:
        return retired
    for slug in retired:
        data.pop(slug, None)
    _write_registry(path, data)
    return retired


def _write_registry(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )


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

#!/usr/bin/env python3
"""Audit MemPalace navigation drawers for a SQL QueryMemory project wing.

To move Alibr data out of `default` / legacy wing `alibr`, use
`scripts/migrate_alibr_project_memory.py` instead.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.aion_env  # noqa: F401

from src.memory.navigation_memory_service import list_drawers, list_wings
from src.memory.project_memory_scope import project_wing

_GENERIC_PATTERNS = (
    re.compile(r"percorso/tabella:\s*unknown", re.I),
    re.compile(r"richiesta:.*esito ok\.?$", re.I),
    re.compile(r"mcperror", re.I),
    re.compile(r"invalid response", re.I),
)


def _is_generic(content: str) -> bool:
    c = (content or "").strip()
    if len(c) < 20:
        return True
    return any(p.search(c) for p in _GENERIC_PATTERNS)


async def _run(args: argparse.Namespace) -> int:
    session = args.session or "audit-cli"
    project = args.project
    wing = project_wing(project)
    print(f"Project: {project}  wing: {wing}  session: {session}")

    if args.list_wings or args.prune_legacy:
        wings = await list_wings(session)
        if args.list_wings:
            print(json.dumps(wings, indent=2, ensure_ascii=False))
        legacy = [
            w
            for w in wings
            if w == "alibr" or (not w.startswith("wing_proj_") and not w.startswith("wing_user_"))
        ]
        if legacy and args.list_wings:
            print("\nLegacy / non-project wings (consider --prune-legacy):")
            for w in legacy:
                print(f"  - {w} ({wings[w]} drawers)")
        if args.prune_legacy:
            from src.memory.navigation_memory_service import prune_legacy_wings

            deleted, skipped = await prune_legacy_wings(
                session, dry_run=args.dry_run
            )
            mode = "dry-run" if args.dry_run else "applied"
            print(f"\nprune_legacy_wings ({mode}): delete={deleted} skipped={skipped}")

    rooms = [None] if not args.room else [args.room]
    all_rows = []
    for room in rooms:
        rows = await list_drawers(
            session,
            project_slug=project,
            room=room,
            limit=args.limit,
        )
        all_rows.extend(rows)

    generic = [r for r in all_rows if _is_generic(r.get("content") or r.get("preview") or "")]
    by_room = Counter((r.get("room") or "?") for r in all_rows)

    print(f"\nDrawers listed: {len(all_rows)}")
    print("By room:", dict(by_room))
    print(f"Flagged generic/low-quality: {len(generic)}")

    if args.json:
        print(json.dumps(all_rows, indent=2, ensure_ascii=False))
        return 0

    for r in generic[: args.show]:
        did = r.get("drawer_id") or r.get("id")
        preview = (r.get("preview") or r.get("content") or "")[:200]
        print(f"\n[GENERIC] {did} room={r.get('room')}\n  {preview}")

    if args.dedupe_hint and len(all_rows) > 1:
        previews = {}
        for r in all_rows:
            key = (r.get("room"), (r.get("content") or r.get("preview") or "")[:120])
            previews.setdefault(key, []).append(r.get("drawer_id"))
        dupes = {k: v for k, v in previews.items() if len(v) > 1}
        if dupes:
            print(f"\nPossible duplicate groups: {len(dupes)} (run mempalace_check_duplicate / delete)")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit MemPalace drawers for a project")
    ap.add_argument("--project", "-p", default="aion_am", help="SQL QueryMemory project slug")
    ap.add_argument("--session", "-s", help="Chat session id for MCP pool (default audit-cli)")
    ap.add_argument("--room", help="Filter single room")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--list-wings", action="store_true", help="List all wings and legacy hints")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show", type=int, default=15, help="Max generic rows to print")
    ap.add_argument("--dedupe-hint", action="store_true")
    ap.add_argument(
        "--prune-legacy",
        action="store_true",
        help="Delete drawers in legacy wings (alibr, non wing_proj_*)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="With --prune-legacy, only list wings that would be pruned",
    )
    args = ap.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

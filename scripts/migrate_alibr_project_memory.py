#!/usr/bin/env python3
"""
Move Alibr-specific navigation memory from `default` / legacy wings into project `alibr`.

- MemPalace: copy drawers to `wing_proj_alibr`, delete from source wing.
- SQL QueryMemory: reassign `cached_sql_queries` from project `default` → `alibr` when text matches.

Company-wide facts stay in KG / `wing_user_*` / `wing_aion_system`; `wing_proj_default` is only
for shared cross-ERP navigation (not Alibr table paths).

Requires MCP mempalace running (same as audit script). Use --dry-run first.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.aion_env  # noqa: F401

from sqlalchemy import select, update

from src.data.engine import get_async_session_maker
from src.data.models import CachedSqlQuery, SqlQueryProject
from src.memory.navigation_memory_service import (
    delete_drawer,
    list_drawers_for_wing,
    list_wings,
)
from src.memory.project_memory_scope import project_wing
from src.memory.sql_query_memory import sql_query_memory
from src.memory.sql_query_memory.scope import default_tenant_id
from src.runtime.mempalace_tool_scope import _LEGACY_WING_NAMES

_ALIBR_MARKERS = re.compile(
    r"(?i)\b("
    r"alibr|alibr_prod|pallet_monge|pallet_secchi|pallet_creati_automa|"
    r"testate_ordini|dettagli_ordini|ordini_clienti|sscc|monge|"
    r"local_postgresql\.alibr"
    r")\b"
)

_LEGACY_SOURCE_WINGS = tuple(_LEGACY_WING_NAMES) + ("wing_proj_default",)


def looks_alibr_related(text: str) -> bool:
    return bool(_ALIBR_MARKERS.search(text or ""))


async def _check_duplicate(
    session_id: str, wing: str, content: str, threshold: float = 0.87
) -> bool:
    from src.memory.ltm_orchestrator import _call_mcp_optional

    raw = await _call_mcp_optional(
        session_id,
        "mempalace_check_duplicate",
        {"content": content, "wing": wing, "threshold": threshold},
    )
    if not raw:
        return False
    try:
        data = json.loads(raw) if raw.strip().startswith("{") else {}
    except json.JSONDecodeError:
        return False
    return bool(data.get("is_duplicate"))


async def _add_drawer_raw(
    session_id: str,
    *,
    wing: str,
    room: str,
    content: str,
    dry_run: bool,
) -> None:
    from src.memory.navigation_memory_service import _call_mempalace

    if dry_run:
        print(f"  [dry-run] add wing={wing} room={room} len={len(content)}")
        return
    await _call_mempalace(
        session_id,
        "mempalace_add_drawer",
        {
            "wing": wing,
            "room": room,
            "content": content[:500],
            "added_by": "migrate_alibr_project",
        },
    )


async def migrate_drawer(
    session_id: str,
    *,
    drawer: Dict[str, Any],
    source_wing: str,
    target_wing: str,
    dry_run: bool,
    force: bool,
) -> str:
    """Return action label: moved | skipped_not_alibr | skipped_dup | error."""
    did = drawer.get("drawer_id") or drawer.get("id")
    room = (drawer.get("room") or "discoveries").strip().lower()
    content = (
        drawer.get("content") or drawer.get("preview") or drawer.get("text") or ""
    ).strip()
    if len(content) < 10:
        return "skipped_empty"
    if (
        not force
        and source_wing == project_wing("default")
        and not looks_alibr_related(content)
    ):
        return "skipped_not_alibr"
    if await _check_duplicate(session_id, target_wing, content):
        if did and not dry_run:
            await delete_drawer(session_id, drawer_id=str(did))
        return "skipped_dup_deleted_source" if did else "skipped_dup"
    await _add_drawer_raw(
        session_id, wing=target_wing, room=room, content=content, dry_run=dry_run
    )
    if did and not dry_run:
        await delete_drawer(session_id, drawer_id=str(did))
    return "moved"


async def migrate_mempalace_wings(
    session_id: str,
    *,
    target_slug: str,
    dry_run: bool,
    force_all_from_default: bool,
) -> Dict[str, int]:
    target_wing = project_wing(target_slug)
    counts: Dict[str, int] = {}

    wings_map = await list_wings(session_id)
    sources = list(_LEGACY_SOURCE_WINGS)
    if project_wing("default") not in sources:
        sources.append(project_wing("default"))

    for source in sources:
        if source == target_wing:
            continue
        n_drawers = wings_map.get(source, 0)
        if n_drawers == 0 and source not in wings_map:
            drawers = await list_drawers_for_wing(session_id, wing=source, limit=500)
        else:
            drawers = await list_drawers_for_wing(session_id, wing=source, limit=500)
        if not drawers:
            continue
        print(
            f"\n=== Source wing `{source}` ({len(drawers)} drawers) → `{target_wing}` ==="
        )
        force = source in _LEGACY_WING_NAMES or (
            source == project_wing("default") and force_all_from_default
        )
        for d in drawers:
            action = await migrate_drawer(
                session_id,
                drawer=d,
                source_wing=source,
                target_wing=target_wing,
                dry_run=dry_run,
                force=force,
            )
            counts[action] = counts.get(action, 0) + 1
            if action == "moved":
                print(f"  moved {d.get('drawer_id')} room={d.get('room')}")
    return counts


async def migrate_sql_query_memory(
    *,
    tenant_id: str,
    target_slug: str,
    dry_run: bool,
    force_all_from_default: bool,
) -> Tuple[int, int]:
    tid = tenant_id or default_tenant_id()
    await sql_query_memory.ensure_project(
        project_slug=target_slug,
        tenant_id=tid,
        display_name="Alibr ERP",
    )
    maker = get_async_session_maker()
    moved = skipped = 0
    async with maker() as session:
        default_row = (
            (
                await session.execute(
                    select(SqlQueryProject).where(
                        SqlQueryProject.tenant_id == tid,
                        SqlQueryProject.slug == "default",
                    )
                )
            )
            .scalars()
            .first()
        )
        target_row = (
            (
                await session.execute(
                    select(SqlQueryProject).where(
                        SqlQueryProject.tenant_id == tid,
                        SqlQueryProject.slug == target_slug,
                    )
                )
            )
            .scalars()
            .first()
        )
        if not default_row or not target_row:
            print("SQL QM: missing default or target project row")
            return 0, 0
        rows = (
            (
                await session.execute(
                    select(CachedSqlQuery).where(
                        CachedSqlQuery.project_id == default_row.id
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            blob = f"{row.user_request}\n{row.sql_text}"
            if not force_all_from_default and not looks_alibr_related(blob):
                skipped += 1
                continue
            if dry_run:
                print(f"  [dry-run] SQL QM id={row.id} → project {target_slug}")
            else:
                await session.execute(
                    update(CachedSqlQuery)
                    .where(CachedSqlQuery.id == row.id)
                    .values(project_id=target_row.id, tenant_id=tid)
                )
            moved += 1
        if not dry_run:
            await session.commit()
    return moved, skipped


async def _run(args: argparse.Namespace) -> int:
    session = args.session or "migrate-alibr-cli"
    target = args.target.strip().lower()
    print(f"Target project: {target}  wing: {project_wing(target)}  session: {session}")
    print(f"dry_run={args.dry_run}  force_all_default={args.force_all_default}")

    if args.sql_only:
        m, s = await migrate_sql_query_memory(
            tenant_id=args.tenant,
            target_slug=target,
            dry_run=args.dry_run,
            force_all_from_default=args.force_all_default,
        )
        print(f"\nSQL QueryMemory: moved={m} skipped_non_alibr={s}")
        return 0

    if not args.mempalace_only:
        m, s = await migrate_sql_query_memory(
            tenant_id=args.tenant,
            target_slug=target,
            dry_run=args.dry_run,
            force_all_from_default=args.force_all_default,
        )
        print(f"\nSQL QueryMemory: moved={m} skipped_non_alibr={s}")

    if not args.sql_only:
        counts = await migrate_mempalace_wings(
            session,
            target_slug=target,
            dry_run=args.dry_run,
            force_all_from_default=args.force_all_default,
        )
        print("\nMemPalace actions:", json.dumps(counts, indent=2))

    if args.prune_legacy_after and not args.dry_run:
        from src.memory.navigation_memory_service import prune_legacy_wings

        deleted, skipped = await prune_legacy_wings(session, dry_run=False)
        print(f"\nPruned legacy wings: {deleted}  skipped: {skipped}")

    print(
        "\nNext: in chat-ui select project `alibr` for Alibr work; keep `default` for "
        "shared company navigation only. Fatti aziendali → KG / wing_user_* (see mempalace_protocol)."
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--session", "-s", help="Chat session id for MCP pool")
    ap.add_argument(
        "--target", default="alibr", help="Target SQL QM / MemPalace project slug"
    )
    ap.add_argument("--tenant", default=None, help="Tenant id (default from env)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--force-all-default",
        action="store_true",
        help="Move every drawer/query from wing_proj_default, not only Alibr-tagged text",
    )
    ap.add_argument("--sql-only", action="store_true")
    ap.add_argument("--mempalace-only", action="store_true")
    ap.add_argument(
        "--prune-legacy-after",
        action="store_true",
        help="Delete legacy wing alibr drawers after migration",
    )
    args = ap.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Remove generic auto-learn MemPalace drawers (Italian template noise)."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.aion_env  # noqa: F401

_NOISY_PATTERNS = (
    re.compile(r"^Percorso verificato per «", re.I),
    re.compile(r"^Entry point per «", re.I),
    re.compile(r"Query validata salvata in QueryMemory", re.I),
)


async def _list_drawers(session_id: str, wing: str) -> list[dict]:
    from src.memory.ltm_orchestrator import _call_mcp_optional

    raw = await _call_mcp_optional(
        session_id,
        "mempalace_list_drawers",
        {"wing": wing},
    )
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict) and isinstance(data.get("drawers"), list):
        return [d for d in data["drawers"] if isinstance(d, dict)]
    return []


def _is_noisy(content: str) -> bool:
    text = (content or "").strip()
    return any(p.search(text) for p in _NOISY_PATTERNS)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Delete noisy MemPalace navigation drawers")
    parser.add_argument("--wing", required=True, help="e.g. wing_proj_aion_am")
    parser.add_argument("--session-id", default="cleanup-script")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    drawers = await _list_drawers(args.session_id, args.wing)
    noisy = [d for d in drawers if _is_noisy(str(d.get("content") or d.get("text") or ""))]
    print(f"wing={args.wing} total={len(drawers)} noisy={len(noisy)}")
    for d in noisy:
        preview = str(d.get("content") or d.get("text") or "")[:120]
        print(f"  - id={d.get('id')} {preview!r}")
    if args.dry_run or not noisy:
        return 0

    from src.memory.ltm_orchestrator import _call_mcp

    for d in noisy:
        drawer_id = d.get("id")
        if drawer_id is None:
            continue
        await _call_mcp(
            args.session_id,
            "mempalace_delete_drawer",
            {"wing": args.wing, "drawer_id": drawer_id},
        )
        print(f"deleted id={drawer_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

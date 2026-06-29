#!/usr/bin/env python3
"""
Migrate chat_memory.db rows into unified aion.db (messages + conversations).
  python scripts/migrate_to_aion_db.py --dry-run
  python scripts/migrate_to_aion_db.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("AION_UNIFIED_DB", "1")


async def main(dry_run: bool) -> int:
    from src.data.bootstrap import ensure_bootstrap_schema
    from src.data.engine import init_engine
    from src.data.history_bridge import UnifiedHistoryBridge

    chat_path = ROOT / "data" / "chat_memory.db"
    if not chat_path.is_file():
        print("[migrate] No data/chat_memory.db — skip.")
        return 0
    conn = sqlite3.connect(str(chat_path))
    conn.row_factory = sqlite3.Row
    msgs = conn.execute(
        "SELECT session_id, profile_name, user_id, role, content, tool_name, tool_call_id "
        "FROM messages ORDER BY id"
    ).fetchall()
    conn.close()
    print(f"[migrate] messages to import: {len(msgs)} dry_run={dry_run}")
    if dry_run:
        return 0
    eng = init_engine()
    await ensure_bootstrap_schema(eng)
    bridge = UnifiedHistoryBridge()
    await bridge.init()
    for m in msgs:
        await bridge.add_message(
            m["session_id"],
            m["role"],
            m["content"],
            profile_name=m["profile_name"] or "default",
            user_id=m["user_id"],
            tool_name=m["tool_name"],
            tool_call_id=m["tool_call_id"],
        )
    print("[migrate] import complete -> data/aion.db")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.dry_run)))

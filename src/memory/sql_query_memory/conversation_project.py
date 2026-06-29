"""Resolve active SQL QueryMemory project from chat conversation metadata."""
from __future__ import annotations

import json
import os
from typing import Optional


def _unified_db_enabled() -> bool:
    return os.getenv("AION_UNIFIED_DB", "1").strip().lower() in ("1", "true", "yes", "on")


async def get_conversation_sql_project(conversation_id: str) -> Optional[str]:
    """Return sql_query_project from Conversation.metadata_json when unified DB is on."""
    cid = (conversation_id or "").strip()
    if not cid or not _unified_db_enabled():
        return None
    try:
        from src.data.engine import get_async_session_maker
        from src.data.models import Conversation

        async with get_async_session_maker()() as session:
            row = await session.get(Conversation, cid)
            if not row or not row.metadata_json:
                return None
            meta = json.loads(row.metadata_json)
            proj = (meta.get("sql_query_project") or "").strip()
            return proj or None
    except Exception:
        return None

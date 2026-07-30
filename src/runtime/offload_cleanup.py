"""Deferred cleanup of offloaded tool results for archived conversations."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import select

from src.data.engine import get_async_session_maker
from src.data.models import Conversation
from src.runtime.tool_offload import cleanup_session_offloads

logger = logging.getLogger("aion.tool_offload")


def _cleanup_settings() -> tuple[bool, int, int]:
    from src.settings import get_settings

    s = get_settings()
    return (
        bool(s.tool_offload_cleanup_enabled),
        max(1, int(s.tool_offload_cleanup_grace_days)),
        max(60, int(s.tool_offload_cleanup_interval_sec)),
    )


async def cleanup_offloads_for_archived_conversations(
    *,
    grace_days: int | None = None,
) -> Dict[str, Any]:
    """Remove session offloads for conversations archived longer than grace_days."""
    enabled, default_grace, _ = _cleanup_settings()
    if not enabled:
        return {"skipped": True, "reason": "disabled"}
    days = grace_days if grace_days is not None else default_grace
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cleaned: List[str] = []
    total_bytes = 0
    async with get_async_session_maker()() as session:
        rows = (
            await session.execute(
                select(Conversation.id, Conversation.archived_at).where(
                    Conversation.archived_at.is_not(None),
                    Conversation.archived_at < cutoff,
                )
            )
        ).all()
    for conv_id, archived_at in rows:
        cid = str(conv_id or "").strip()
        if not cid:
            continue
        freed = cleanup_session_offloads(cid)
        if freed:
            cleaned.append(cid)
            total_bytes += freed
    if cleaned:
        logger.info(
            "offload cleanup job conversations=%s freed_bytes=%s grace_days=%s",
            len(cleaned),
            total_bytes,
            days,
        )
    return {
        "cleaned_conversations": len(cleaned),
        "freed_bytes": total_bytes,
        "grace_days": days,
    }


async def offload_cleanup_loop() -> None:
    """Background loop — run deferred offload cleanup periodically."""
    import asyncio

    while True:
        enabled, _, interval = _cleanup_settings()
        if enabled:
            try:
                await cleanup_offloads_for_archived_conversations()
            except Exception as exc:
                logger.warning("offload cleanup loop error: %s", exc)
        await asyncio.sleep(interval)

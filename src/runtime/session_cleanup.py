"""Automated cleanup and retention policy for chat sessions/conversations."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import delete, select, update

from src.data.engine import get_async_session_maker
from src.data.models import Conversation
from src.runtime.tool_offload import cleanup_session_offloads

logger = logging.getLogger("aion.session_cleanup")


def _session_cleanup_settings() -> tuple[int, int, bool]:
    from src.settings import get_settings

    s = get_settings()
    max_days = max(0, int(s.session_cleanup_max_age_days))
    interval = max(60, int(s.session_cleanup_interval_sec))
    hard_delete = bool(s.session_cleanup_hard_delete)
    return max_days, interval, hard_delete


def _delete_session_sandbox(session_id: str) -> bool:
    """Safely delete sandbox workspace files on disk for the session."""
    data_dir = Path(os.getenv("AION_DATA_DIR", "data"))
    session_dir = data_dir / "sessions" / session_id
    deleted = False
    if session_dir.exists() and session_dir.is_dir():
        try:
            shutil.rmtree(session_dir, ignore_errors=True)
            deleted = True
        except Exception as err:
            logger.warning("Error deleting sandbox dir %s: %s", session_dir, err)
    return deleted


def _is_protected_conversation(conv: Conversation) -> bool:
    """Return True if conversation is starred/pinned or explicitly protected."""
    try:
        import json

        meta = json.loads(conv.metadata_json or "{}")
        if meta.get("favorite") in (True, "true", 1, "1"):
            return True
        if meta.get("pinned") in (True, "true", 1, "1"):
            return True
    except Exception:
        pass
    return False


async def cleanup_expired_sessions(
    *,
    max_age_days: int | None = None,
    hard_delete: bool | None = None,
    keep_min_recent: int = 1,
) -> Dict[str, Any]:
    """Clean up or archive sessions older than max_age_days.

    Protections:
    - Favorite / pinned conversations are never deleted or archived.
    - At least `keep_min_recent` (default: 1) most recent conversations per user
      are kept so users returning after inactive periods never encounter a blank/empty state.
    """
    cfg_days, _, cfg_hard = _session_cleanup_settings()
    days = max_age_days if max_age_days is not None else cfg_days
    is_hard = hard_delete if hard_delete is not None else cfg_hard

    if days <= 0:
        return {"skipped": True, "reason": "disabled"}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    processed: List[str] = []
    freed_bytes = 0
    data_dir = Path(os.getenv("AION_DATA_DIR", "data"))

    async with get_async_session_maker()() as session:
        # Find active or non-cleaned conversations whose updated_at < cutoff
        query = select(Conversation).where(Conversation.updated_at < cutoff)
        if not is_hard:
            # Soft delete (archiving): process only currently unarchived conversations
            query = query.where(Conversation.archived_at.is_(None))

        result = await session.execute(query)
        candidates = result.scalars().all()

        # Identify protected recent conversation IDs per user
        protected_recent_ids: set[str] = set()
        if keep_min_recent > 0 and candidates:
            user_keys = {(c.tenant_id, c.user_id) for c in candidates}
            for t_id, u_id in user_keys:
                recent_q = select(Conversation.id).where(
                    Conversation.tenant_id == t_id,
                    Conversation.user_id == u_id,
                )
                if not is_hard:
                    recent_q = recent_q.where(Conversation.archived_at.is_(None))
                recent_q = (
                    recent_q.order_by(Conversation.updated_at.desc())
                    .limit(keep_min_recent)
                )
                recent_res = await session.execute(recent_q)
                for r in recent_res.all():
                    if r[0]:
                        protected_recent_ids.add(str(r[0]).strip())

        to_process: List[Conversation] = []
        for conv in candidates:
            if _is_protected_conversation(conv):
                continue
            if conv.id in protected_recent_ids:
                continue
            to_process.append(conv)

        now = datetime.now(timezone.utc)

        for conv in to_process:
            conv_id = conv.id
            try:
                # Release MCP session pool if active
                try:
                    from src.mcp_manager import mcp_manager

                    await mcp_manager.release_session(conv_id)
                except Exception as mcp_err:
                    logger.debug(
                        "MCP release session failed for %s: %s", conv_id, mcp_err
                    )

                # Clean offload files
                offload_freed = cleanup_session_offloads(conv_id)
                if offload_freed:
                    freed_bytes += offload_freed

                if is_hard:
                    # Clean sandbox disk folder
                    _delete_session_sandbox(conv_id)

                    # Hard delete DB record (cascade handles messages/steps/attachments)
                    await session.execute(
                        delete(Conversation).where(Conversation.id == conv_id)
                    )
                else:
                    # Soft delete: archive
                    await session.execute(
                        update(Conversation)
                        .where(Conversation.id == conv_id)
                        .values(archived_at=now)
                    )

                processed.append(conv_id)
            except Exception as item_err:
                logger.error(
                    "Error during session cleanup for %s: %s", conv_id, item_err
                )

        if is_hard:
            # Clean orphaned session folders on disk older than cutoff (not in DB or deleted earlier)
            sessions_root = data_dir / "sessions"
            if sessions_root.exists() and sessions_root.is_dir():
                all_db_ids_res = await session.execute(select(Conversation.id))
                active_db_ids = {
                    str(r[0]).strip() for r in all_db_ids_res.all() if r[0]
                }
                for item in sessions_root.iterdir():
                    if item.is_dir() and item.name not in active_db_ids:
                        try:
                            st_mtime = item.stat().st_mtime
                            mtime_dt = datetime.fromtimestamp(st_mtime, tz=timezone.utc)
                            if mtime_dt < cutoff:
                                shutil.rmtree(item, ignore_errors=True)
                                if item.name not in processed:
                                    processed.append(item.name)
                        except Exception as err:
                            logger.warning(
                                "Error deleting orphaned session dir %s: %s", item, err
                            )

        await session.commit()

    if processed:
        action = "hard_deleted" if is_hard else "archived"
        logger.info(
            "Session cleanup job complete: %s=%d sessions max_age_days=%d freed_offload_bytes=%d",
            action,
            len(processed),
            days,
            freed_bytes,
        )

    return {
        "processed_conversations": len(processed),
        "hard_delete": is_hard,
        "max_age_days": days,
        "freed_bytes": freed_bytes,
        "session_ids": processed,
    }


async def session_cleanup_loop() -> None:
    """Background loop — run session cleanup periodically."""
    while True:
        max_days, interval, _ = _session_cleanup_settings()
        if max_days > 0:
            try:
                await cleanup_expired_sessions()
            except Exception as exc:
                logger.warning("Session cleanup loop error: %s", exc)
        await asyncio.sleep(interval)

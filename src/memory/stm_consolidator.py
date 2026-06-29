import logging
import os
from typing import Optional

from ..api.history import history_manager
from .ltm_orchestrator import ltm_orchestrator

logger = logging.getLogger("aion.memory.stm_consolidator")


async def consolidate(
    session_id: str,
    profile_name: str,
    user_id: str,
    *,
    prune_after: bool = False,
) -> dict:
    """
    Batch STM → LTM: unpromoted rows → extractor (batch) → mark promoted; optional prune.
    """
    rows = await history_manager.fetch_unpromoted_rows(session_id, profile_name)
    if not rows:
        return {"status": "empty", "promoted": 0}

    lines = []
    for r in rows:
        role = r.get("role", "")
        content = (r.get("content") or "").strip()
        tool_name = r.get("tool_name")
        if role == "tool":
            lines.append(f"[tool:{tool_name}] {content}")
        else:
            lines.append(f"{role.upper()}: {content}")
    transcript = "\n".join(lines)

    await ltm_orchestrator.extract_and_persist(
        session_id,
        user_id,
        f"[BATCH transcript session={session_id} profile={profile_name}]\n"
        + transcript[:16000],
        "",
        mode="batch",
    )
    ids = [r["id"] for r in rows if r.get("id") is not None]
    await history_manager.mark_promoted(ids)
    if prune_after or os.getenv("AION_STM_PRUNE_AFTER_CONSOLIDATE", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        keep = int(os.getenv("AION_STM_PRUNE_KEEP", "50"))
        await history_manager.prune_old(session_id, profile_name, keep_last_n=keep)
    logger.info("STM consolidated: promoted %d messages", len(ids))
    return {"status": "ok", "promoted": len(ids)}


async def maybe_consolidate_periodic(
    session_id: str,
    profile_name: str,
    user_id: str,
    user_turn_count: int,
) -> Optional[dict]:
    every = int(os.getenv("AION_STM_CONSOLIDATE_EVERY", "10"))
    if every <= 0:
        return None
    if user_turn_count <= 0 or user_turn_count % every != 0:
        return None
    return await consolidate(session_id, profile_name, user_id, prune_after=False)

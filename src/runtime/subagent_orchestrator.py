"""Run isolated mini-sessions for subagent delegation (Claude-style)."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ..agent_profile import profile_manager
from ..session_workspace import ensure_session_dirs, sync_parent_uploads_to_child

logger = logging.getLogger("aion.subagent")


async def run_subagent_task(
    subagent_profile: str,
    task: str,
    user_id: str,
    parent_conversation_id: str,
) -> str:
    """
    Spawns a sub-session using an existing agent profile.
    The sub-session is isolated and returns the final result.
    """
    profile = profile_manager.get_profile(subagent_profile)
    if not profile:
        return f"[subagent] Profile not found: {subagent_profile}"

    child_session = f"sub_{profile.slug}_{uuid.uuid4().hex[:10]}"
    ensure_session_dirs(child_session)
    sync_meta = sync_parent_uploads_to_child(parent_conversation_id, child_session)
    if sync_meta.get("errors"):
        logger.warning(
            "subagent upload sync parent=%s child=%s: %s",
            parent_conversation_id,
            child_session,
            sync_meta,
        )
    from src.main import get_agent

    agent, resolved = await get_agent(
        profile.slug, session_id=child_session, user_id=user_id
    )
    from src.agent_pipeline import AgentPipeline

    pipe = AgentPipeline(agent, child_session, resolved, user_id=user_id)
    out: List[str] = []
    async for chunk in pipe.run_stream(task):
        if chunk.get("type") == "token":
            out.append(chunk.get("content") or "")
    return "".join(out)[:32000]

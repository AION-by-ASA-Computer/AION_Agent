"""Internal API: Pi worker tool invocation bridge."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("aion.pi_tools")

router = APIRouter(prefix="/internal/pi", tags=["internal-pi"])


class PiToolInvokeBody(BaseModel):
    session_id: str
    profile: str = Field(default="generic_assistant")
    user_id: str = Field(default="default")
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    call_id: Optional[str] = None


def _check_secret(x_aion_pi_secret: Optional[str]) -> None:
    expected = (os.getenv("AION_PI_WORKER_SECRET") or "").strip()
    if not expected:
        return
    if (x_aion_pi_secret or "").strip() != expected:
        raise HTTPException(status_code=403, detail="Invalid Pi worker secret")


@router.post("/tools/invoke")
async def invoke_pi_tool(
    body: PiToolInvokeBody,
    x_aion_pi_secret: Optional[str] = Header(None, alias="X-Aion-Pi-Secret"),
):
    _check_secret(x_aion_pi_secret)
    from src.runtime.pi_runtime.tool_invoke import invoke_aion_tool_for_pi
    from src.runtime.turn_compaction import truncate_tool_result

    try:
        content = await invoke_aion_tool_for_pi(
            session_id=body.session_id,
            profile_name=body.profile,
            user_id=body.user_id,
            tool_name=body.tool_name,
            arguments=body.arguments,
        )
        truncated = truncate_tool_result(content, tool_name=body.tool_name)
        is_truncated = truncated != content
        logger.debug(
            "Pi tool invoke ok tool=%s session=%s chars=%d truncated=%s",
            body.tool_name,
            body.session_id[:8],
            len(truncated),
            is_truncated,
        )
        return {
            "content": truncated,
            "is_error": False,
            "truncated": is_truncated,
        }
    except Exception as exc:
        logger.warning(
            "Pi tool invoke failed tool=%s session=%s: %s",
            body.tool_name,
            body.session_id[:8],
            exc,
        )
        return {
            "content": str(exc),
            "is_error": True,
            "truncated": False,
        }

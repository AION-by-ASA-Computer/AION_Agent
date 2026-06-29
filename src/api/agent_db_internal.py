"""
Internal HTTP hooks for the Agent DB MCP subprocess (LTM sync via MemPalace MCP).

Set AION_AGENT_DB_LTM_SYNC_URL (e.g. http://127.0.0.1:8000/internal/agent-db/sync-drawer)
and AION_AGENT_DB_INTERNAL_SECRET (same value in MCP env and API env).
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .ltm_admin import _call, _validate_wing_room

logger = logging.getLogger("aion.api.agent_db_internal")

router = APIRouter(tags=["internal-agent-db"])


class StructuredDrawerBody(BaseModel):
    wing: str = Field(default="structured_data", max_length=64)
    room: str = Field(..., min_length=1, max_length=80)
    content: str = Field(..., min_length=10, max_length=20000)


def _require_secret(x_secret: str | None) -> None:
    expected = (os.getenv("AION_AGENT_DB_INTERNAL_SECRET") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="AION_AGENT_DB_INTERNAL_SECRET not configured on API host",
        )
    if not x_secret or x_secret != expected:
        raise HTTPException(status_code=403, detail="Invalid Agent DB sync secret")


@router.post("/internal/agent-db/sync-drawer")
async def agent_db_sync_drawer(
    body: StructuredDrawerBody,
    x_aion_agent_db_secret: str | None = Header(None, alias="X-AION-Agent-DB-Secret"),
):
    _require_secret(x_aion_agent_db_secret)
    _validate_wing_room(body.wing, body.room)
    try:
        text = await _call(
            "mempalace_add_drawer",
            {"wing": body.wing, "room": body.room, "content": body.content},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("mempalace_add_drawer failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"ok": True, "text": text}

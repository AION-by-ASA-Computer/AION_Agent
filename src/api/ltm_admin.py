"""
Admin REST API for MemPalace (LTM) — thin wrappers over MCP tools.
"""
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..mcp_manager import mcp_manager
from ..memory.ltm_audit import append_ltm_audit
logger = logging.getLogger("aion.api.ltm_admin")

router = APIRouter(prefix="/ltm", tags=["ltm"])

_WING_ROOM_RE = re.compile(r"^[a-z0-9_\-]+$")


def _tool_result_to_text(res: Any) -> str:
    if not hasattr(res, "content") or not res.content:
        return str(res)
    parts = []
    for c in res.content:
        parts.append(getattr(c, "text", None) or str(c))
    return "\n".join(parts)


async def _call(tool: str, arguments: Dict[str, Any]) -> str:
    try:
        async with mcp_manager.session_context("mempalace") as session:
            result = await session.call_tool(tool, arguments=arguments)
        return _tool_result_to_text(result)
    except Exception as e:
        logger.error("MCP tool %s failed: %s", tool, e)
        raise HTTPException(status_code=502, detail=f"{tool}: {e}") from e


async def _call_optional(tool: str, arguments: Dict[str, Any]) -> str | None:
    try:
        async with mcp_manager.session_context("mempalace") as session:
            result = await session.call_tool(tool, arguments=arguments)
        return _tool_result_to_text(result)
    except Exception:
        return None


def _validate_wing_room(wing: str, room: Optional[str] = None) -> None:
    if not _WING_ROOM_RE.match(wing):
        raise HTTPException(status_code=400, detail="Invalid wing name")
    if room is not None and not _WING_ROOM_RE.match(room):
        raise HTTPException(status_code=400, detail="Invalid room name")


# --- GET (read-only) ---


@router.get("/status")
async def ltm_status():
    return {"text": await _call("mempalace_status", {})}


@router.get("/wings")
async def ltm_wings():
    return {"text": await _call("mempalace_list_wings", {})}


@router.get("/rooms")
async def ltm_rooms(wing: str = Query(..., description="Wing id")):
    _validate_wing_room(wing)
    return {"text": await _call("mempalace_list_rooms", {"wing": wing})}


@router.get("/taxonomy")
async def ltm_taxonomy():
    return {"text": await _call("mempalace_get_taxonomy", {})}


@router.get("/search")
async def ltm_search(
    q: str = Query(..., description="Search query"),
    wing: Optional[str] = Query(None),
    room: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    args: Dict[str, Any] = {"query": q, "limit": limit}
    if wing:
        _validate_wing_room(wing)
        args["wing"] = wing
    if room:
        if not wing:
            raise HTTPException(status_code=400, detail="wing required when room is set")
        _validate_wing_room(wing, room)
        args["room"] = room
    return {"text": await _call("mempalace_search", args)}


@router.get("/kg/query")
async def ltm_kg_query(
    entity: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    as_of: Optional[str] = Query(None),
):
    args: Dict[str, Any] = {}
    if entity:
        args["entity"] = entity
    if subject:
        args["subject"] = subject
    if as_of:
        args["as_of"] = as_of
    if not args:
        raise HTTPException(status_code=400, detail="Provide entity or subject")
    return {"text": await _call("mempalace_kg_query", args)}


@router.get("/kg/timeline")
async def ltm_kg_timeline(entity: str = Query(...)):
    return {"text": await _call("mempalace_kg_timeline", {"entity": entity})}


@router.get("/kg/stats")
async def ltm_kg_stats():
    return {"text": await _call("mempalace_kg_stats", {})}


@router.get("/graph/stats")
async def ltm_graph_stats():
    return {"text": await _call("mempalace_graph_stats", {})}


@router.get("/diary/{agent_name}")
async def ltm_diary_read(agent_name: str, last_n: int = Query(20, ge=1, le=200)):
    return {
        "text": await _call(
            "mempalace_diary_read", {"agent_name": agent_name, "last_n": last_n}
        )
    }


@router.get("/tools")
async def ltm_list_tools():
    """Debug: list MCP tool names for MemPalace."""
    async with mcp_manager.session_context("mempalace") as session:
        tools_result = await session.list_tools()
        return {"tools": [t.name for t in tools_result.tools]}


@router.get("/agents")
async def ltm_list_agents():
    """MemPalace v3 agent registry (tool `mempalace_list_agents` when available)."""
    txt = await _call_optional("mempalace_list_agents", {})
    if txt is not None:
        return {"text": txt}
    return {
        "text": await _call("mempalace_list_wings", {}),
        "note": "mempalace_list_agents unavailable; returned wings as fallback",
    }


@router.get("/agents/{name}/diary")
async def ltm_agent_diary(name: str, last_n: int = Query(30, ge=1, le=200)):
    return {
        "text": await _call(
            "mempalace_diary_read", {"agent_name": name, "last_n": last_n}
        )
    }


# --- Write ---


class DrawerCreate(BaseModel):
    wing: str
    room: str
    content: str = Field(..., min_length=10)


@router.post("/drawer")
async def ltm_add_drawer(body: DrawerCreate):
    _validate_wing_room(body.wing, body.room)
    if len(body.content) > 20000:
        raise HTTPException(status_code=400, detail="Content too long")
    append_ltm_audit(
        "mempalace_add_drawer",
        {"wing": body.wing, "room": body.room, "len": len(body.content)},
    )
    return {
        "text": await _call(
            "mempalace_add_drawer",
            {"wing": body.wing, "room": body.room, "content": body.content},
        )
    }


@router.delete("/drawer/{drawer_id}")
async def ltm_delete_drawer(drawer_id: str):
    append_ltm_audit("mempalace_delete_drawer", {"drawer_id": drawer_id})
    return {"text": await _call("mempalace_delete_drawer", {"drawer_id": drawer_id})}


class TripleCreate(BaseModel):
    subject: str
    predicate: str
    object: str
    valid_from: Optional[str] = None


@router.post("/kg/triple")
async def ltm_kg_add(body: TripleCreate):
    args: Dict[str, Any] = {
        "subject": body.subject,
        "predicate": body.predicate,
        "object": body.object,
    }
    if body.valid_from:
        args["valid_from"] = body.valid_from
    append_ltm_audit("mempalace_kg_add", {k: args[k] for k in ("subject", "predicate", "object")})
    return {"text": await _call("mempalace_kg_add", args)}


class InvalidateBody(BaseModel):
    subject: str
    predicate: str
    object: str


@router.post("/kg/invalidate")
async def ltm_kg_invalidate(body: InvalidateBody):
    append_ltm_audit(
        "mempalace_kg_invalidate",
        {"subject": body.subject, "predicate": body.predicate, "object": body.object},
    )
    return {
        "text": await _call(
            "mempalace_kg_invalidate",
            {
                "subject": body.subject,
                "predicate": body.predicate,
                "object": body.object,
            },
        )
    }


"""Deep Research API — /research/* (Caddy strips /api prefix in production)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.identity import sanitize_user_id
from src.research.handler import (
    deep_research_enabled,
    get_research_handler,
    new_research_session_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["research"])

_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


class ResearchStartRequest(BaseModel):
    query: str
    max_rounds: int = Field(default=0, ge=0, le=20)
    max_time: int = Field(default=300, ge=60, le=1800)
    category: Optional[str] = None
    session_id: Optional[str] = None
    chat_session_id: Optional[str] = None


def resolve_research_owner(
    auth: ChatAuthIdentity,
    x_aion_user_id: Optional[str] = None,
) -> str:
    """Match /chat user resolution: JWT wins; else X-AION-User-Id (open chat)."""
    if auth.via == "chat_token" and auth.identifier:
        return sanitize_user_id(auth.identifier)
    return sanitize_user_id(x_aion_user_id or auth.identifier or "default")


async def research_owner(
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> str:
    return resolve_research_owner(auth, x_aion_user_id)


def _validate_session_id(session_id: str) -> None:
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(400, "Invalid session ID format")


def _require_owner(session_id: str, owner: str) -> None:
    handler = get_research_handler()
    if not handler.owns(session_id, owner):
        raise HTTPException(404, "No research found for this session")


@router.get("/research/enabled")
async def research_enabled_flag():
    from src.research.handler import deep_research_enabled

    return {"enabled": deep_research_enabled()}


@router.get("/research/active")
async def research_active(
    chat_session_id: Optional[str] = Query(None, max_length=128),
    owner: str = Depends(research_owner),
):
    if not deep_research_enabled():
        return {"active": []}
    handler = get_research_handler()
    return {"active": handler.list_active_for_owner(owner, chat_session_id=chat_session_id)}


@router.get("/research/status/{session_id}")
async def research_status(
    session_id: str,
    owner: str = Depends(research_owner),
):
    _validate_session_id(session_id)
    _require_owner(session_id, owner)
    status = get_research_handler().get_status(session_id)
    if status is None:
        raise HTTPException(404, "No research found")
    return status


@router.post("/research/cancel/{session_id}")
async def research_cancel(
    session_id: str,
    owner: str = Depends(research_owner),
):
    _validate_session_id(session_id)
    _require_owner(session_id, owner)
    ok = get_research_handler().cancel_research(session_id)
    return {"cancelled": ok}


@router.get("/research/report/{session_id}")
async def research_report(
    session_id: str,
    owner: str = Depends(research_owner),
):
    _validate_session_id(session_id)
    _require_owner(session_id, owner)
    html = get_research_handler().get_report_html(session_id)
    if not html:
        raise HTTPException(404, "Report not found")
    return HTMLResponse(content=html)


@router.get("/research/library")
async def research_library(
    search: str = Query(""),
    sort: str = Query("recent"),
    limit: int = Query(50, ge=1, le=200),
    archived: Optional[bool] = Query(None),
    chat_session_id: Optional[str] = Query(None, max_length=128),
    owner: str = Depends(research_owner),
):
    items = get_research_handler().list_library(
        owner,
        search=search,
        sort=sort,
        limit=limit,
        archived=archived,
        chat_session_id=chat_session_id,
    )
    return {"research": items, "total": len(items)}


@router.get("/research/detail/{session_id}")
async def research_detail(
    session_id: str,
    owner: str = Depends(research_owner),
):
    _validate_session_id(session_id)
    _require_owner(session_id, owner)
    data = get_research_handler().load_json(session_id)
    if not data:
        raise HTTPException(404, "Not found")
    return data


@router.post("/research/{session_id}/archive")
async def research_archive(
    session_id: str,
    archived: bool = Query(True),
    owner: str = Depends(research_owner),
):
    _validate_session_id(session_id)
    _require_owner(session_id, owner)
    ok = get_research_handler().set_archived(session_id, archived)
    if not ok:
        raise HTTPException(404, "Not found")
    return {"ok": True, "id": session_id, "archived": archived}


@router.delete("/research/{session_id}")
async def research_delete(
    session_id: str,
    owner: str = Depends(research_owner),
):
    _validate_session_id(session_id)
    _require_owner(session_id, owner)
    deleted = get_research_handler().delete_research(session_id)
    return {"deleted": deleted}


@router.post("/research/start")
async def research_start(
    body: ResearchStartRequest,
    owner: str = Depends(research_owner),
):
    if not deep_research_enabled():
        raise HTTPException(403, "Deep research is disabled")
    query = (body.query or "").strip()
    if not query:
        raise HTTPException(400, "query is required")
    session_id = (body.session_id or new_research_session_id()).strip()
    _validate_session_id(session_id)
    chat_session_id = (body.chat_session_id or "").strip()
    effective_rounds = body.max_rounds if body.max_rounds > 0 else _env_max_rounds()
    handler = get_research_handler()
    try:
        handler.start_research(
            session_id,
            query,
            max_time=body.max_time,
            max_rounds=effective_rounds,
            category=body.category,
            owner=owner,
            chat_session_id=chat_session_id,
        )
    except RuntimeError as e:
        raise HTTPException(429, str(e)) from e
    return {"session_id": session_id, "status": "running", "query": query}


def _env_max_rounds() -> int:
    import os

    try:
        return int(os.getenv("AION_DEEP_RESEARCH_MAX_ROUNDS", "8"))
    except ValueError:
        return 8


@router.get("/research/stream/{session_id}")
async def research_stream(
    session_id: str,
    owner: str = Depends(research_owner),
):
    _validate_session_id(session_id)
    _require_owner(session_id, owner)
    handler = get_research_handler()

    async def _generate():
        last_progress = None
        while True:
            status = handler.get_status(session_id)
            if status is None:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                return
            st = status.get("status", "")
            progress = status.get("progress") or {}
            activities = status.get("activities") or []
            payload = {**progress, "status": st, "activities": activities}
            if payload != last_progress:
                last_progress = payload
                yield f"data: {json.dumps(payload)}\n\n"
            if st != "running":
                final = {
                    "status": st,
                    "final": True,
                    **progress,
                    "activities": activities,
                }
                task = handler._active_tasks.get(session_id, {})
                if st == "error" and task.get("result"):
                    final["error"] = str(task["result"])[:500]
                yield f"data: {json.dumps(final)}\n\n"
                return
            await asyncio.sleep(1.5)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/research/result-peek/{session_id}")
async def research_result_peek(
    session_id: str,
    owner: str = Depends(research_owner),
):
    _validate_session_id(session_id)
    _require_owner(session_id, owner)
    handler = get_research_handler()
    result = handler.get_result(session_id)
    if result is None:
        data = handler.load_json(session_id)
        if not data:
            raise HTTPException(404, "No research result available")
        return {
            "result": data.get("result", ""),
            "sources": data.get("sources", []),
            "raw_findings": data.get("raw_findings", []),
            "category": data.get("category") or "",
        }
    return {
        "result": result,
        "sources": handler.get_sources(session_id) or [],
        "raw_findings": handler.get_raw_findings(session_id) or [],
        "category": "",
    }


@router.post("/research/result/{session_id}")
async def research_result_consume(
    session_id: str,
    owner: str = Depends(research_owner),
):
    _validate_session_id(session_id)
    _require_owner(session_id, owner)
    handler = get_research_handler()
    result = handler.get_result(session_id)
    sources = handler.get_sources(session_id) or []
    raw_findings = handler.get_raw_findings(session_id) or []
    if result is None:
        raise HTTPException(404, "No research result available")
    handler.clear_result(session_id)
    return {"result": result, "sources": sources, "raw_findings": raw_findings}


@router.post("/research/{session_id}/hide-image")
async def research_hide_image(
    session_id: str,
    request: Request,
    owner: str = Depends(research_owner),
):
    _validate_session_id(session_id)
    _require_owner(session_id, owner)
    body = await request.json()
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "url required")
    ok = get_research_handler().hide_image(session_id, url)
    if not ok:
        raise HTTPException(404, "Not found")
    return {"ok": True}


@router.post("/research/{session_id}/unhide-images")
async def research_unhide_images(
    session_id: str,
    owner: str = Depends(research_owner),
):
    _validate_session_id(session_id)
    _require_owner(session_id, owner)
    ok = get_research_handler().unhide_all_images(session_id)
    if not ok:
        raise HTTPException(404, "Not found")
    return {"ok": True}

"""Plan execution API — /plan-execution/* (background jobs + SSE progress)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.api.research import resolve_research_owner
from src.identity import sanitize_user_id
from src.plan_execution.handler import (
    get_plan_execution_handler,
    plan_execution_enabled,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["plan-execution"])

_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


class PlanExecutionStartRequest(BaseModel):
    plan_id: str = Field(..., min_length=4, max_length=128)
    chat_session_id: Optional[str] = Field(None, max_length=128)
    profile_name: Optional[str] = Field(None, max_length=128)
    run_id: Optional[str] = None


async def plan_execution_owner(
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> str:
    return resolve_research_owner(auth, x_aion_user_id)


def _validate_run_id(run_id: str) -> None:
    if not _RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(400, "Invalid run ID format")


def _require_owner(run_id: str, owner: str) -> None:
    handler = get_plan_execution_handler()
    if not handler.owns(run_id, owner):
        raise HTTPException(404, "No plan execution found for this run")


@router.get("/plan-execution/enabled")
async def plan_execution_enabled_flag():
    return {"enabled": plan_execution_enabled()}


@router.get("/plan-execution/active")
async def plan_execution_active(
    chat_session_id: Optional[str] = Query(None, max_length=128),
    owner: str = Depends(plan_execution_owner),
):
    if not plan_execution_enabled():
        return {"active": []}
    handler = get_plan_execution_handler()
    return {"active": handler.list_active_for_owner(owner, chat_session_id=chat_session_id)}


@router.get("/plan-execution/runs")
async def plan_execution_runs(
    chat_session_id: Optional[str] = Query(None, max_length=128),
    limit: int = Query(20, ge=1, le=50),
    owner: str = Depends(plan_execution_owner),
):
    if not plan_execution_enabled():
        return {"runs": []}
    handler = get_plan_execution_handler()
    return {
        "runs": handler.list_runs_for_owner(
            owner,
            chat_session_id=chat_session_id,
            limit=limit,
        )
    }


@router.get("/plan-execution/status/{run_id}")
async def plan_execution_status(
    run_id: str,
    owner: str = Depends(plan_execution_owner),
):
    _validate_run_id(run_id)
    _require_owner(run_id, owner)
    status = get_plan_execution_handler().get_status(run_id)
    if status is None:
        raise HTTPException(404, "No plan execution found")
    return status


@router.post("/plan-execution/start")
async def plan_execution_start(
    body: PlanExecutionStartRequest,
    owner: str = Depends(plan_execution_owner),
):
    if not plan_execution_enabled():
        raise HTTPException(403, "Plan execution is disabled")
    plan_id = (body.plan_id or "").strip()
    if not plan_id:
        raise HTTPException(400, "plan_id is required")
    handler = get_plan_execution_handler()
    try:
        out = handler.start_plan_execution(
            plan_id,
            owner=owner,
            chat_session_id=(body.chat_session_id or "").strip(),
            profile_name=(body.profile_name or "").strip(),
        )
    except RuntimeError as e:
        raise HTTPException(429, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return out


@router.post("/plan-execution/cancel/{run_id}")
async def plan_execution_cancel(
    run_id: str,
    owner: str = Depends(plan_execution_owner),
):
    _validate_run_id(run_id)
    _require_owner(run_id, owner)
    ok = get_plan_execution_handler().cancel_plan_execution(run_id)
    return {"cancelled": ok}


@router.get("/plan-execution/stream/{run_id}")
async def plan_execution_stream(
    run_id: str,
    owner: str = Depends(plan_execution_owner),
):
    _validate_run_id(run_id)
    _require_owner(run_id, owner)
    handler = get_plan_execution_handler()

    async def _generate():
        last_progress = None
        stream_seq = 0
        while True:
            status = handler.get_status(run_id)
            if status is None:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                return
            st = status.get("status", "")
            progress = status.get("progress") or {}
            activities = status.get("activities") or []
            tasks = status.get("tasks") or []
            payload = {
                **progress,
                "status": st,
                "activities": activities,
                "tasks": tasks,
                "plan_id": status.get("plan_id", ""),
            }
            if payload != last_progress:
                last_progress = payload
                yield f"data: {json.dumps(payload)}\n\n"
            if st != "running":
                final = {
                    "status": st,
                    "final": True,
                    **progress,
                    "activities": activities,
                    "tasks": tasks,
                    "plan_id": status.get("plan_id", ""),
                }
                data = handler.load_json(run_id)
                if st == "error" and data and data.get("result"):
                    final["error"] = str(data["result"])[:500]
                if st == "done" and data:
                    final["summary"] = data.get("result") or ""
                    final["deliverable_path"] = data.get("deliverable_path")
                yield f"data: {json.dumps(final)}\n\n"
                return
            stream_seq = await handler.wait_stream_update(run_id, stream_seq, timeout=0.5)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/plan-execution/result/{run_id}")
async def plan_execution_result(
    run_id: str,
    owner: str = Depends(plan_execution_owner),
):
    _validate_run_id(run_id)
    _require_owner(run_id, owner)
    handler = get_plan_execution_handler()
    result = handler.get_result(run_id)
    if result is None:
        data = handler.load_json(run_id)
        if not data:
            raise HTTPException(404, "No plan execution result available")
        return {
            "summary": data.get("result", ""),
            "plan_id": data.get("plan_id", ""),
            "deliverable_path": data.get("deliverable_path"),
        }
    return {
        "summary": result,
        "plan_id": handler.load_json(run_id).get("plan_id", "") if handler.load_json(run_id) else "",
        "deliverable_path": handler.get_deliverable_path(run_id),
    }

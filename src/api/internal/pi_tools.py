"""Internal API: Pi worker tool invocation bridge."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
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


class PiCompactionSummarizeBody(BaseModel):
    session_id: str
    transcript: str
    previous_summary: str = ""
    file_ops: Dict[str, Any] = Field(default_factory=dict)
    custom_instructions: str = ""
    previous_details: Dict[str, Any] = Field(default_factory=dict)


def _check_secret(x_aion_pi_secret: Optional[str]) -> None:
    expected = (os.getenv("AION_PI_WORKER_SECRET") or "").strip()
    if not expected:
        return
    if (x_aion_pi_secret or "").strip() != expected:
        raise HTTPException(status_code=403, detail="Invalid Pi worker secret")


@router.get("/ledger")
async def get_pi_ledger(
    session_id: str = Query(..., min_length=4),
    x_aion_pi_secret: Optional[str] = Header(None, alias="X-Aion-Pi-Secret"),
):
    _check_secret(x_aion_pi_secret)
    from src.runtime.pi_runtime.pi_compaction import render_ledger_for_pi

    table = render_ledger_for_pi(session_id)
    return {"ok": True, "table": table}


@router.post("/compaction/summarize")
async def pi_compaction_summarize(
    body: PiCompactionSummarizeBody,
    x_aion_pi_secret: Optional[str] = Header(None, alias="X-Aion-Pi-Secret"),
):
    _check_secret(x_aion_pi_secret)
    from src.runtime.pi_runtime.pi_compaction import summarize_for_pi_compaction

    try:
        result = summarize_for_pi_compaction(
            session_id=body.session_id,
            transcript=body.transcript,
            previous_summary=body.previous_summary,
            file_ops=body.file_ops,
            custom_instructions=body.custom_instructions,
            previous_details=body.previous_details or None,
        )
        return {"ok": True, **result}
    except Exception as exc:
        logger.warning(
            "Pi compaction summarize failed session=%s: %s",
            body.session_id[:8],
            exc,
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/tools/invoke")
async def invoke_pi_tool(
    body: PiToolInvokeBody,
    x_aion_pi_secret: Optional[str] = Header(None, alias="X-Aion-Pi-Secret"),
):
    _check_secret(x_aion_pi_secret)
    from src.runtime.pi_runtime.tool_invoke import invoke_aion_tool_for_pi
    from src.runtime.tool_offload import process_tool_result_for_context

    started = time.monotonic()
    try:
        content = await invoke_aion_tool_for_pi(
            session_id=body.session_id,
            profile_name=body.profile,
            user_id=body.user_id,
            tool_name=body.tool_name,
            arguments=body.arguments,
        )
        dur_ms = int((time.monotonic() - started) * 1000)
        context_text, details = process_tool_result_for_context(
            content,
            session_id=body.session_id,
            tool_name=body.tool_name,
            call_id=body.call_id,
            arguments=body.arguments,
            dur_ms=dur_ms,
        )
        is_truncated = context_text != content
        from src.runtime.mcp_tool_result import classify_tool_result_text

        is_error, normalized = classify_tool_result_text(context_text, body.tool_name)
        if normalized:
            context_text = normalized
        logger.debug(
            "Pi tool invoke ok tool=%s session=%s chars=%d truncated=%s error=%s offloaded=%s",
            body.tool_name,
            body.session_id[:8],
            len(context_text),
            is_truncated,
            is_error,
            bool(details),
        )
        payload: Dict[str, Any] = {
            "content": context_text,
            "is_error": is_error,
            "truncated": is_truncated,
        }
        if details:
            payload["details"] = details
        return payload
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

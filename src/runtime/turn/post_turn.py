"""Post-turn: outcome classification, fallback answer, final persistence."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def finalize_turn_outcome(
    *,
    session_id: str,
    profile_name: str,
    stop_reason: str,
    final_text: str,
    full_reasoning: str,
    tool_calls: int,
    tool_events: int,
    turn_new_messages: List[Any],
    turn_context_stats: Dict[str, Any],
    agent: Any,
    pending_db_steps: List[Dict[str, Any]],
    timeline_builder: Any,
    plan_intercepts: int = 0,
    reasoning_effort: Optional[str] = None,
    max_reasoning_chars: Optional[int] = None,
    max_reasoning_events: Optional[int] = None,
) -> tuple[str, Optional[Dict[str, Any]]]:
    """
    Classify turn outcome and optionally build tool-result fallback text.
    Returns (final_text, turn_outcome_sse_chunk or None).
    """
    if not final_text and tool_calls > 0:
        try:
            from src.runtime.turn_answer_fallback import build_tool_result_fallback

            fb = build_tool_result_fallback(pending_db_steps)
            if fb:
                final_text = fb
        except Exception as fb_exc:
            logger.debug("tool result fallback skipped: %s", fb_exc)

    try:
        from src.runtime.turn_compaction import get_llm_step_count
        from src.runtime.turn_diagnostics import (
            classify_turn_outcome,
            record_turn_outcome,
        )

        llm_steps_done = get_llm_step_count()
    except Exception:
        llm_steps_done = 0

    turn_outcome = classify_turn_outcome(
        session_id=session_id,
        profile=profile_name,
        stop_reason=stop_reason,
        final_text=final_text,
        full_reasoning=full_reasoning,
        tool_calls_count=tool_calls,
        tool_events_count=tool_events,
        new_messages=turn_new_messages,
        context_stats=turn_context_stats,
        max_agent_steps=getattr(agent, "max_agent_steps", None),
        llm_steps=llm_steps_done,
        plan_intercepts=plan_intercepts,
        reasoning_effort=reasoning_effort,
        max_reasoning_chars=max_reasoning_chars,
        max_reasoning_events=max_reasoning_events,
    )
    record_turn_outcome(turn_outcome)
    if not final_text and turn_outcome.get("code") == "plan_created":
        final_text = str(turn_outcome.get("suggested_final_text") or "").strip()
    elif not final_text and turn_outcome.get("suggested_final_text"):
        final_text = str(turn_outcome.get("suggested_final_text") or "").strip()
    warn = turn_outcome.get("user_visible_warning")
    sse_chunk: Optional[Dict[str, Any]] = None
    if warn:
        code = turn_outcome.get("code")
        details = turn_outcome.get("details") or {}
        if not final_text:
            final_text = str(warn).strip()
        if timeline_builder is not None:
            try:
                timeline_builder.apply_turn_outcome(
                    str(warn),
                    code=str(code) if code else None,
                    details=details if isinstance(details, dict) else {},
                )
            except Exception as tl_exc:
                logger.debug("timeline turn_outcome skipped: %s", tl_exc)
        sse_chunk = {
            "type": "turn_outcome",
            "code": code,
            "message": warn,
            "details": details,
        }
    return final_text, sse_chunk

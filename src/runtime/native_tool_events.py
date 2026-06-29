"""Bridge eventi tool per esecutori nativi Haystack → tool_event_bus (SSE / chat-ui)."""

from __future__ import annotations

import logging
from typing import Any, Dict

from src.runtime.context import get_context
from src.runtime.tool_call_ids import new_tool_call_id
from src.runtime.tool_events import tool_event_bus

logger = logging.getLogger("aion.native_tool_events")


def emit_tool_start(session_id: str, name: str, inp: Dict[str, Any]) -> str:
    """Emit tool_start; returns call_id for matching end/error."""
    call_id = new_tool_call_id()
    emit_native_tool_event(
        session_id,
        {"type": "tool_start", "id": call_id, "name": name, "input": inp},
    )
    return call_id


def emit_tool_end(session_id: str, name: str, call_id: str, output: str) -> None:
    emit_native_tool_event(
        session_id,
        {"type": "tool_end", "id": call_id, "name": name, "output": output},
    )


def emit_tool_error(session_id: str, name: str, call_id: str, error: str) -> None:
    emit_native_tool_event(
        session_id,
        {"type": "tool_error", "id": call_id, "name": name, "error": error},
    )


def emit_native_tool_event(session_id: str, payload: Dict[str, Any]) -> None:
    """Schedula put_event sul loop del contesto agente (thread-safe come MCP)."""
    ctx = get_context()
    loop = ctx.get("loop")
    if loop is not None:
        try:
            loop.call_soon_threadsafe(tool_event_bus.put_event, session_id, payload)
            return
        except RuntimeError as e:
            logger.warning("emit_native_tool_event: call_soon_threadsafe failed: %s", e)
    logger.warning(
        "emit_native_tool_event: missing loop in agent context; dropping event session=%s type=%s name=%s",
        session_id,
        payload.get("type"),
        payload.get("name"),
    )

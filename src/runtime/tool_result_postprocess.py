"""Shared post-processing for tool results (Haystack return path + SSE)."""

from __future__ import annotations

from typing import Optional


def apply_tool_result_postprocess(
    output: object,
    *,
    session_id: Optional[str],
    profile_slug: Optional[str],
    tool_name: str,
    event_type: str = "tool_end",
) -> str:
    """Apply reminders/nudges consistently for LLM and UI."""
    from src.runtime.datasource_memory_mode import maybe_append_same_turn_reminder

    text = str(output or "")
    return maybe_append_same_turn_reminder(
        session_id=session_id,
        profile_slug=profile_slug,
        tool_name=tool_name,
        event_type=event_type,
        output=text,
    )

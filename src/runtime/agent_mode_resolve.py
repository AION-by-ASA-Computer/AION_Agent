"""Resolve effective agent mode for chat requests (Plan Mode, Deep Research, internal triggers)."""
from __future__ import annotations

import os


def resolve_agent_mode(
    agent_mode: str | None,
    plan_mode: bool | None = None,
    *,
    deep_research_mode: bool | None = None,
    message_source: str = "user_input",
) -> str:
    """
    Post-approval execution must run in normal mode with full tool access.

    ``internal_trigger`` (orchestration_plan_approved follow-up) always forces ``normal``
    so mutating tools (sandbox_run_python_file, mark_task_completed, …) are not blocked.
    """
    src = (message_source or "user_input").strip()
    if src in ("internal_trigger", "scheduled_trigger"):
        return "normal"

    resolved = (agent_mode or "normal").strip().lower() or "normal"

    if plan_mode is True:
        return "plan"
    if plan_mode is False and resolved == "plan":
        return "normal"

    if deep_research_mode is True:
        return "deep_research"
    if deep_research_mode is False and resolved == "deep_research":
        return "normal"
    if resolved == "deep_research":
        return "deep_research"

    env_default = (os.getenv("AION_DEFAULT_AGENT_MODE") or "normal").strip().lower()
    if resolved == "normal" and env_default in ("plan", "ask", "debug", "deep_research"):
        return env_default
    return resolved

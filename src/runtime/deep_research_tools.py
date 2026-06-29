"""Deep Research in-process tools — merged on every agent when enabled (like orchestration)."""

from __future__ import annotations

import logging
from typing import Any, List

logger = logging.getLogger(__name__)

DEEP_RESEARCH_BUILTIN_TOOL_NAMES: tuple[str, ...] = (
    "trigger_research",
    "manage_research",
)


def merge_builtin_deep_research_tools(
    tools: List[Any],
    session_id: str,
    user_id: str,
    profile=None,
) -> List[Any]:
    """Append trigger_research / manage_research unless already present."""
    from src.research.handler import deep_research_enabled

    if not deep_research_enabled():
        return tools

    from src.runtime.native_tools.factory_table import (
        build_manage_research_tool,
        build_trigger_research_tool,
    )

    existing = {getattr(t, "name", None) for t in tools}
    builders = (
        build_trigger_research_tool,
        build_manage_research_tool,
    )
    for builder in builders:
        try:
            haystack_tool = builder(session_id, user_id, profile)
        except ValueError as exc:
            logger.debug("deep research tool skipped: %s", exc)
            continue
        name = getattr(haystack_tool, "name", None)
        if name and name not in existing:
            tools.append(haystack_tool)
            existing.add(name)
    return tools

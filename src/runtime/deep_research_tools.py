"""Deep Research in-process tools (``trigger_research`` / ``manage_research``).

Merged into the agent tool list by ``src.main.build_all_tools``. Availability
depends only on the Deep Research connector and on the chat mode, never on the
other MCP servers / native groups of the profile (the research job is a
self-contained pipeline with its own web search and LLM calls):

- **Deep Research mode** (chat-ui agent-mode selector, ``agent_mode=deep_research``):
  always available, whatever the profile.
- **Normal mode** (and the other modes): available only when the profile has
  the connector, i.e. the ``deep_research`` native tool group or an MCP server
  slug in :data:`DEEP_RESEARCH_MCP_SLUGS`.

When merged, the tools are always *resident* (full schema on the first model
call, see ``src.runtime.tool_exposure.RESIDENT_NATIVE_GROUPS``) so the model can
call ``trigger_research`` on its first step without a ``tool_search`` round.
See ``docs/integrations/deep-research.md``.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

DEEP_RESEARCH_BUILTIN_TOOL_NAMES: tuple[str, ...] = (
    "trigger_research",
    "manage_research",
)

# Native tool group id (see config/native_tool_registry.yaml) gating these tools.
DEEP_RESEARCH_GROUP = "deep_research"

# Agent mode id (chat-ui selector / resolve_agent_mode) that always enables them.
DEEP_RESEARCH_MODE = "deep_research"

# MCP slugs treated as "the Deep Research connector" on a profile. Older
# profiles list ``deep_research`` under ``mcp_servers`` instead of
# ``native_tool_groups`` (there is no such MCP server: the job runs in-process),
# and must keep the capability.
DEEP_RESEARCH_MCP_SLUGS: frozenset[str] = frozenset({"deep_research"})


def profile_wants_deep_research(profile: Any) -> bool:
    """True when ``profile`` has the Deep Research connector.

    The connector is the ``deep_research`` native tool group or a matching MCP
    slug in ``mcp_servers``. ``None`` profiles have no connector.
    """
    if profile is None:
        return False
    groups = getattr(profile, "native_tool_groups", None) or []
    if DEEP_RESEARCH_GROUP in groups:
        return True
    servers = getattr(profile, "mcp_servers", None) or []
    return any(s in DEEP_RESEARCH_MCP_SLUGS for s in servers)


def deep_research_tools_allowed(profile: Any, agent_mode: Optional[str] = None) -> bool:
    """Gate for ``trigger_research`` / ``manage_research`` on one agent.

    Args:
        profile: the agent profile (may be ``None``).
        agent_mode: the *resolved* agent mode of the agent being built
            (``normal``, ``plan``, ``deep_research`` …).

    Returns:
        True in Deep Research mode (any profile) or when the profile has the
        connector; False when Deep Research is disabled globally
        (``AION_DEEP_RESEARCH_ENABLED=0``).
    """
    from src.research.handler import deep_research_enabled

    if not deep_research_enabled():
        return False
    if (agent_mode or "").strip().lower() == DEEP_RESEARCH_MODE:
        return True
    return profile_wants_deep_research(profile)


def merge_builtin_deep_research_tools(
    tools: List[Any],
    session_id: str,
    user_id: str,
    profile=None,
    agent_mode: Optional[str] = None,
) -> List[Any]:
    """Append trigger_research / manage_research unless already present.

    No-op when :func:`deep_research_tools_allowed` is False for this
    profile/mode. ``load_native_tools`` already builds them for profiles with
    the native group; this merge covers Deep Research mode on profiles without
    the connector and the legacy MCP-slug connector. The list is mutated in
    place and also returned for convenience.
    """
    if not deep_research_tools_allowed(profile, agent_mode):
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

"""MCP: delegate work to configured subagents (isolated sessions)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from fastmcp import FastMCP

from src.runtime.delegate_subagent import delegate_to_subagent_async

mcp = FastMCP("AION Subagents")


@mcp.tool()
async def delegate_to_subagent(
    name: str,
    task: str,
    parent_profile: str = "aion_std",
    user_id: str = "default",
    parent_conversation_id: str = "inline",
    attachment_ids: str = "",
) -> str:
    """
    Run a sub-agent with profile ``name`` (YAML slug in ``config/profiles``).
    ``parent_profile`` is reserved for logging; parent file session is ``parent_conversation_id``.
    ``attachment_ids``: comma-separated (optional, future use).
    """
    _ = parent_profile, attachment_ids
    return await delegate_to_subagent_async(
        subagent_profile=name,
        task=task,
        user_id=user_id,
        parent_session_id=parent_conversation_id,
    )


if __name__ == "__main__":
    mcp.run()

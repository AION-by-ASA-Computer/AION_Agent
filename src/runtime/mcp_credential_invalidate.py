"""Invalidate pooled MCP workers after per-user credential changes."""

from __future__ import annotations

import logging

from src.identity import sanitize_user_id

logger = logging.getLogger("aion.mcp_credential_invalidate")


async def invalidate_mcp_credentials_runtime(
    user_id: str,
    server_slug: str,
    *,
    tenant_id: str = "default",
) -> int:
    """Restart pooled stdio workers so the next tool call respawns with fresh env."""
    from src.mcp_manager import mcp_manager

    stopped = await mcp_manager.restart_workers_for_user(
        user_id,
        server_slug=server_slug,
        tenant_id=tenant_id,
    )
    if stopped:
        logger.info(
            "Restarted %s MCP worker(s) for user=%s server=%s after credential change",
            stopped,
            sanitize_user_id(user_id),
            server_slug,
        )
    return stopped

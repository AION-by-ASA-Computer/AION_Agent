"""
Pre-seeding della cache token di mcp-remote rimosso (deprecato).

AION utilizza esclusivamente l'autenticazione header-based (Authorization: Bearer <token>)
per i server remote-bridge, passando il token al momento dello spawn del processo mcp-remote.
Pertanto, la cache PKCE interna di mcp-remote non viene più usata o popolata, eliminando
le desincronizzazioni.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("aion.mcp_remote_cache")


async def seed_mcp_remote_token_cache(
    user_id: str,
    server_slug: str,
    token_data: Dict[str, Any],
    oauth_cfg: Dict[str, Any],
    *,
    server_url: Optional[str] = None,
) -> bool:
    """
    (Deprecato) Non effettua più il seeding della cache locale di mcp-remote.
    mcp-remote riceve il token esclusivamente tramite header HTTP (Authorization: Bearer).
    """
    logger.debug("mcp-remote cache seed bypassed: token passed via header instead")
    return True

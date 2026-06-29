# mcp_servers/agent_db/ltm_notifier.py
"""Optional HTTP callback to sync Agent DB summaries into MemPalace (via API → MCP)."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request

logger = logging.getLogger("aion.agent_db.ltm_notifier")


def sanitize_drawer_room(key: str) -> str:
    s = re.sub(r"[^a-z0-9_\-]+", "_", (key or "").lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return (s[:80] or "drawer")


def post_structured_drawer_sync(content: str, key: str, wing: str = "structured_data") -> None:
    """
    POST to FastAPI internal route if AION_AGENT_DB_LTM_SYNC_URL and
    AION_AGENT_DB_INTERNAL_SECRET are set.
    """
    url = (os.getenv("AION_AGENT_DB_LTM_SYNC_URL") or "").strip()
    secret = (os.getenv("AION_AGENT_DB_INTERNAL_SECRET") or "").strip()
    if not url or not secret:
        return

    room = sanitize_drawer_room(key)
    payload = json.dumps(
        {"wing": wing, "room": room, "content": content},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-AION-Agent-DB-Secret": secret,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=float(os.getenv("AION_AGENT_DB_LTM_HTTP_TIMEOUT", "8"))) as resp:
            _ = resp.read()
    except urllib.error.HTTPError as e:
        logger.warning("LTM sync HTTP %s: %s", e.code, e.reason)
    except Exception as e:
        logger.warning("LTM sync failed: %s", e)

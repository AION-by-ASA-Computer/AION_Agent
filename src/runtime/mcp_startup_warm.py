"""Pre-avvio MCP stdio al boot API (pool caldo prima della prima chat)."""
from __future__ import annotations

import logging
import os
from typing import List, Set

from ..agent_profile import profile_manager
from ..mcp_manager import BOOTSTRAP_SESSION_ID, mcp_manager

logger = logging.getLogger("aion.mcp_startup_warm")


def startup_warm_enabled() -> bool:
    return os.getenv("AION_MCP_STARTUP_WARM", "1").lower() not in ("0", "false", "no")


def startup_warm_async() -> bool:
    return os.getenv("AION_MCP_STARTUP_WARM_ASYNC", "0").lower() in ("1", "true", "yes")


def _warm_all_registry_stdio() -> bool:
    return os.getenv("AION_MCP_STARTUP_WARM_ALL", "0").lower() in ("1", "true", "yes")


def _collect_startup_server_slugs() -> List[str]:
    servers: Set[str] = set()
    mcp_manager.load_registry()

    if _warm_all_registry_stdio():
        for name, cfg in (mcp_manager._registry or {}).items():
            if name.startswith("_") or not cfg:
                continue
            t = (cfg.get("type") or "stdio").lower()
            if t in ("sse", "in_process"):
                continue
            if mcp_manager.stdio_entrypoint_missing(name, cfg):
                continue
            servers.add(name)
    else:
        raw_profiles = (
            os.getenv("AION_MCP_STARTUP_WARM_PROFILES")
            or os.getenv("AION_MCP_STARTUP_WARM_PROFILE")
            or "aion_std,generic_assistant"
        )
        profile_manager.load_all_if_stale()
        if raw_profiles.strip() == "*":
            for row in profile_manager.list_profiles() or []:
                p = profile_manager.get_profile(row.get("name") or row.get("slug") or "")
                if p:
                    servers.update(p.mcp_servers or [])
        for token in raw_profiles.split(","):
            slug = token.strip()
            if not slug or slug == "*":
                continue
            profile = profile_manager.get_profile(slug)
            if profile:
                servers.update(profile.mcp_servers or [])
            else:
                logger.warning("MCP startup warm: profilo %r non trovato, skip", slug)

    out = sorted(s for s in servers if s and s != "aion_subagents")
    return out


async def warm_mcp_at_startup() -> None:
    """Avvia handshake MCP per i server del profilo (o tutto il registry)."""
    pool_on = os.getenv("AION_MCP_POOL", "1").lower() not in ("0", "false", "no")
    if not startup_warm_enabled() or not pool_on:
        logger.info(
            "MCP startup warm skipped (AION_MCP_STARTUP_WARM=%s, AION_MCP_POOL=%s)",
            os.getenv("AION_MCP_STARTUP_WARM", "1"),
            os.getenv("AION_MCP_POOL", "0"),
        )
        return

    servers = _collect_startup_server_slugs()
    if not servers:
        logger.info("MCP startup warm: nessun server stdio da avviare")
        return

    tenant_id = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"
    profile_slug = (
        (os.getenv("AION_MCP_STARTUP_WARM_PROFILES") or "aion_std").split(",")[0].strip()
        or "generic_assistant"
    )
    user_ids = _startup_warm_user_ids()

    logger.info(
        "MCP startup warm: avvio %d server(s) per user(s)=%s tenant=%s (profilo ref=%s)",
        len(servers),
        ",".join(user_ids),
        tenant_id,
        profile_slug,
    )
    mcp_manager._ensure_cleanup_task()
    for user_id in user_ids:
        await mcp_manager.warm_session(
            BOOTSTRAP_SESSION_ID,
            servers,
            profile_slug=profile_slug,
            user_id=user_id,
            tenant_id=tenant_id,
        )
    logger.info("MCP startup warm completato (%d server, %d user)", len(servers), len(user_ids))


def _startup_warm_user_ids() -> List[str]:
    """Utenti per cui pre-riscaldare il pool MCP (deve includere chi chatta in dev)."""
    raw = (os.getenv("AION_MCP_STARTUP_WARM_USER_IDS") or "").strip()
    if raw:
        return list(dict.fromkeys(u.strip() for u in raw.split(",") if u.strip()))
    single = (os.getenv("AION_MCP_STARTUP_WARM_USER_ID") or "").strip()
    if single:
        return [single]
    setup = (os.getenv("AION_SETUP_CHAT_IDENTIFIER") or "").strip()
    if setup:
        return [setup]
    return ["default"]

"""Probe MCP servers for a profile (runtime errors surfaced to chat-ui)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..agent_profile import profile_manager
from ..mcp_manager import mcp_manager

logger = logging.getLogger("aion.mcp_health")

# session_id -> {server_slug: error_message}
_last_probe_errors: Dict[str, Dict[str, str]] = {}


def get_last_mcp_load_errors(session_id: str) -> Dict[str, str]:
    return dict(_last_probe_errors.get(session_id) or {})


def record_mcp_load_error(session_id: str, server_slug: str, error: str) -> None:
    if not session_id or not server_slug:
        return
    _last_probe_errors.setdefault(session_id, {})[server_slug] = (
        error or "unknown error"
    )[:2000]


def clear_mcp_load_errors(session_id: str, server_slug: Optional[str] = None) -> None:
    if server_slug:
        _last_probe_errors.get(session_id, {}).pop(server_slug, None)
    else:
        _last_probe_errors.pop(session_id, None)


async def probe_mcp_server(
    server_slug: str,
    *,
    user_id: str,
    session_id: str,
    profile_slug: str = "",
) -> Dict[str, Any]:
    """Handshake + list_tools; returns {ok, tool_count?, error?}."""
    mcp_manager.load_registry()
    if server_slug not in mcp_manager._registry:
        return {
            "server_slug": server_slug,
            "ok": False,
            "error": f"Server '{server_slug}' non presente nel registry MCP.",
        }
    cfg = mcp_manager.get_server_config(server_slug) or {}

    # I server in_process non necessitano probe: i tool sono registrati nel processo
    # principale e sono sempre disponibili.
    server_type = (cfg.get("type") or "stdio").lower()
    if server_type == "in_process":
        return {
            "server_slug": server_slug,
            "ok": True,
            "tool_count": 0,  # in-process: conteggio non disponibile via list_tools
            "note": "Server in-process: i tool sono registrati nativamente nel processo API.",
        }

    old_ctx = mcp_manager._session_ctx.get(session_id)
    slug = old_ctx[0] if (old_ctx and old_ctx[0]) else profile_slug
    mcp_manager._session_ctx[session_id] = (slug, user_id, "default")
    try:
        async with mcp_manager.session_context(
            server_slug, chat_session_id=session_id
        ) as session:
            result = await session.list_tools()
        tools = getattr(result, "tools", None) or []
        clear_mcp_load_errors(session_id, server_slug)
        return {
            "server_slug": server_slug,
            "ok": True,
            "tool_count": len(tools),
            "command": cfg.get("command"),
            "args": cfg.get("args"),
        }
    except Exception as e:
        msg = str(e).strip() or type(e).__name__
        record_mcp_load_error(session_id, server_slug, msg)
        hint = _hint_for_error(server_slug, cfg, msg)
        return {
            "server_slug": server_slug,
            "ok": False,
            "error": _clean_error_message(msg),
            "hint": hint,
            "command": cfg.get("command"),
            "args": cfg.get("args"),
        }


def classify_mcp_error(
    error_msg: str, cfg: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """Classifies an MCP error message into category, user-friendly description, and actionable hint."""
    cfg = cfg or {}
    low = (error_msg or "").lower()

    # 1. Timeout / Unreachable
    if (
        "timeout" in low
        or "timed out" in low
        or "taskgroup" in low
        or "sub-exception" in low
        or "connection refused" in low
        or "econnrefused" in low
    ):
        return {
            "error_type": "timeout",
            "category": "Connection Timeout / Unreachable",
            "error": "The MCP server is unreachable or timed out during handshake.",
            "hint": "Check that the endpoint is active, network is reachable, and the server starts within the timeout limit.",
        }

    # 2. Host environment / Missing executable / Module not found
    if (
        "not found" in low
        or "enoent" in low
        or "command not found" in low
        or "cannot find module" in low
        or "modulenotfounderror" in low
        or "no such file" in low
    ):
        cmd = cfg.get("command") or ""
        return {
            "error_type": "executable_missing",
            "category": "Host Environment / Executable Error",
            "error": f"Executable or package dependency not found ({cmd or 'runtime'}).",
            "hint": f"Ensure '{cmd or 'runtime'}' and required dependencies are installed on the server and available in PATH.",
        }

    # 3. Authentication / Unauthorized
    if (
        "401" in low
        or "403" in low
        or "unauthorized" in low
        or "forbidden" in low
        or "invalid_client" in low
        or "invalid_grant" in low
        or "api key" in low
    ):
        return {
            "error_type": "auth_failed",
            "category": "Authentication Failed",
            "error": "Invalid, expired, or missing API credentials / OAuth token.",
            "hint": "Verify credentials in MCP Hub (Org env) or user profile integrations.",
        }

    # 4. Process crash / Syntax error / Script failure
    if (
        "exit code" in low
        or "closed" in low
        or "process terminated" in low
        or "traceback" in low
        or "syntaxerror" in low
        or "typeerror" in low
    ):
        return {
            "error_type": "process_crashed",
            "category": "MCP Process Crash",
            "error": f"MCP server process crashed during initialization ({error_msg[:160]}).",
            "hint": "Check server command line arguments, runtime parameters, and server logs.",
        }

    # 5. General error
    return {
        "error_type": "general_error",
        "category": "MCP Connection Error",
        "error": error_msg[:200] if error_msg else "Unknown probe error occurred.",
        "hint": "Check command, arguments, environment variables, and logs in MCP Hub.",
    }


def _clean_error_message(msg: str) -> str:
    classified = classify_mcp_error(msg)
    return classified["error"]


def _hint_for_error(server_slug: str, cfg: Dict[str, Any], msg: str) -> str:
    classified = classify_mcp_error(msg, cfg)
    return classified["hint"]


def format_session_mcp_errors(
    session_id: str, profile_name: str
) -> List[Dict[str, Any]]:
    """Errori MCP registrati per sessione, filtrati sul profilo (payload chat-ui)."""
    profile = profile_manager.get_profile(profile_name)
    profile_slugs = {
        s
        for s in (profile.mcp_servers if profile else []) or []
        if s and s != "aion_subagents"
    }
    rows: List[Dict[str, Any]] = []
    for slug, err in get_last_mcp_load_errors(session_id).items():
        if slug not in profile_slugs:
            continue
        cfg = mcp_manager.get_server_config(slug) or {}
        hint = _hint_for_error(slug, cfg, err)
        clean_err = _clean_error_message(err)
        rows.append(
            {
                "server_slug": slug,
                "display_name": slug.replace("-", " ").title(),
                "error": clean_err,
                "hint": hint,
                "reason": "runtime_error",
                "message": hint or clean_err or "MCP unavailable",
            }
        )
    return rows


async def probe_profile_mcp_servers(
    profile_name: str,
    *,
    user_id: str,
    session_id: str,
) -> List[Dict[str, Any]]:
    profile = profile_manager.get_profile(profile_name)
    if not profile:
        return [
            {
                "server_slug": "",
                "ok": False,
                "error": f"Profile '{profile_name}' not found.",
            }
        ]
    out: List[Dict[str, Any]] = []
    for slug in profile.mcp_servers or []:
        if not slug or slug == "aion_subagents":
            continue
        out.append(
            await probe_mcp_server(
                slug,
                user_id=user_id,
                session_id=session_id,
                profile_slug=profile.slug,
            )
        )
    return out

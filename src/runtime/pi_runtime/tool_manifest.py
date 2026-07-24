"""Build OpenAI-style tool manifest for Pi worker from AION tools."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aion.pi_tool_manifest")


@dataclass
class PiToolEntry:
    name: str
    description: str
    parameters: Dict[str, Any]
    source: str  # "mcp" | "native"
    server_name: Optional[str] = None


_SESSION_TOOL_REGISTRY: Dict[str, Dict[str, PiToolEntry]] = {}


def get_session_tool_registry(session_id: str) -> Dict[str, PiToolEntry]:
    return _SESSION_TOOL_REGISTRY.get(session_id) or {}


def clear_session_tool_registry(session_id: str) -> None:
    _SESSION_TOOL_REGISTRY.pop(session_id, None)


def tools_to_pi_manifest(
    session_id: str,
    tools: List[Any],
    *,
    blocked: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    """Convert already-built Haystack tools into Pi manifest JSON."""
    from src.runtime.long_run_mode import long_run_blocked_tool_names

    blocked_names = blocked if blocked is not None else long_run_blocked_tool_names()
    registry: Dict[str, PiToolEntry] = {}
    manifest: List[Dict[str, Any]] = []

    for tool in tools:
        name = getattr(tool, "name", None) or ""
        if not name or name in blocked_names:
            continue
        params = getattr(tool, "parameters", None) or {
            "type": "object",
            "properties": {},
        }
        if not isinstance(params, dict):
            params = {"type": "object", "properties": {}}
        desc = getattr(tool, "description", None) or f"Tool {name}"
        fn = getattr(tool, "function", None)
        source = "native"
        server_name: Optional[str] = None
        fn_name = getattr(fn, "__name__", "") if fn is not None else ""
        if fn is not None:
            sn = getattr(fn, "server_name", None)
            if sn:
                source = "mcp"
                server_name = str(sn)
        if source != "mcp" and fn_name.startswith("aion_mcp_x_"):
            source = "mcp"

        entry = PiToolEntry(
            name=name,
            description=str(desc),
            parameters=params,
            source=source,
            server_name=server_name,
        )
        registry[name] = entry
        manifest.append(
            {
                "name": entry.name,
                "description": entry.description,
                "parameters": entry.parameters,
                "source": entry.source,
                "server_name": entry.server_name,
            }
        )

    _SESSION_TOOL_REGISTRY[session_id] = registry
    return manifest


async def build_tool_manifest(
    session_id: str,
    profile: Any,
    user_id: str,
) -> List[Dict[str, Any]]:
    """Discover tools and return JSON-serializable manifest for Pi."""
    from src.main import build_all_tools

    tools = await build_all_tools(session_id, profile, user_id=user_id)
    return tools_to_pi_manifest(session_id, tools)


def write_tool_manifest(session_id: str, manifest: List[Dict[str, Any]]) -> Path:
    from src.runtime.long_run_mode import pi_session_dir

    agent_dir = Path(pi_session_dir(session_id))
    agent_dir.mkdir(parents=True, exist_ok=True)
    path = agent_dir / "tool_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def resolve_mcp_server_for_tool(
    session_id: str,
    profile: Any,
    tool_name: str,
) -> Optional[str]:
    """Find MCP server name hosting ``tool_name``."""
    entry = get_session_tool_registry(session_id).get(tool_name)
    if entry and entry.server_name:
        return entry.server_name

    from src.mcp_manager import mcp_manager

    for server_name in profile.mcp_servers or []:
        try:
            tools = await mcp_manager.list_tools_pooled(session_id, server_name)
            names = {t.name for t in tools.tools}
            if tool_name in names:
                return server_name
        except Exception:
            continue
    return None

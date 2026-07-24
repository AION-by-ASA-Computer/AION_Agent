"""Invoke AION tools from the Pi worker HTTP bridge (parity with Haystack path)."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("aion.pi_tool_invoke")


async def _ensure_mcp_session_context(
    session_id: str,
    profile_name: str,
    user_id: str,
) -> None:
    from src.mcp_manager import mcp_manager
    from src.runtime.session_context import SessionContext

    if mcp_manager.get_session_context(session_id):
        return
    mcp_manager.set_session_context(
        session_id,
        SessionContext(
            profile_slug=profile_name,
            user_id=user_id,
            tenant_id="default",
            conversation_id=session_id,
        ),
    )


async def _resolve_mcp_server(
    session_id: str,
    profile: Any,
    tool_name: str,
) -> Optional[str]:
    from src.runtime.pi_runtime.tool_manifest import (
        get_session_tool_registry,
        resolve_mcp_server_for_tool,
    )

    entry = get_session_tool_registry(session_id).get(tool_name)
    if entry and entry.server_name:
        return entry.server_name
    return await resolve_mcp_server_for_tool(session_id, profile, tool_name)


async def _invoke_mcp_tool(
    *,
    session_id: str,
    profile_name: str,
    user_id: str,
    server_name: str,
    tool_name: str,
    arguments: Dict[str, Any],
) -> str:
    from src.mcp_manager import mcp_manager
    from src.runtime.mcp_tool_args import prepare_mcp_tool_arguments
    from src.runtime.mcp_tool_result import (
        classify_tool_result_text,
        format_mcp_raw_result,
    )
    from src.runtime.skill_profile_gate import block_skills_hub_tool_if_needed
    from src.runtime.sql_query_project_scope import (
        apply_sql_query_project_scope,
        block_project_list_tool,
    )

    prepared, preflight_err = prepare_mcp_tool_arguments(tool_name, dict(arguments))
    if preflight_err:
        return preflight_err

    skill_block = block_skills_hub_tool_if_needed(
        server_name, tool_name, session_id, prepared
    )
    if skill_block:
        return skill_block

    list_block = block_project_list_tool(tool_name, session_id)
    if list_block:
        return list_block

    prepared = apply_sql_query_project_scope(
        tool_name, prepared, session_id=session_id
    )

    raw = await mcp_manager.call_tool_pooled(
        session_id,
        server_name,
        tool_name,
        prepared,
    )
    content = format_mcp_raw_result(raw)
    _, normalized = classify_tool_result_text(content, tool_name)
    return normalized or content


async def _invoke_native_tool(
    *,
    session_id: str,
    profile: Any,
    profile_name: str,
    user_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
) -> str:
    from src.main import build_all_tools

    tools = await build_all_tools(session_id, profile, user_id=user_id)
    tool = next((t for t in tools if getattr(t, "name", None) == tool_name), None)
    if tool is None:
        raise RuntimeError(f"Unknown tool: {tool_name}")
    fn = getattr(tool, "function", None)
    if fn is None or not callable(fn):
        raise RuntimeError(f"Tool not callable: {tool_name}")

    fn_name = getattr(fn, "__name__", "")
    if fn_name.startswith("aion_mcp_x_"):
        server = await _resolve_mcp_server(session_id, profile, tool_name)
        if not server:
            raise RuntimeError(f"No MCP server for tool {tool_name}")
        return await _invoke_mcp_tool(
            session_id=session_id,
            profile_name=profile_name,
            user_id=user_id,
            server_name=server,
            tool_name=tool_name,
            arguments=arguments,
        )

    result = fn(**arguments)
    if inspect.isawaitable(result):
        result = await result
    elif asyncio.iscoroutine(result):
        result = await result
    return result if isinstance(result, str) else json.dumps(result, default=str)


async def invoke_aion_tool_for_pi(
    *,
    session_id: str,
    profile_name: str,
    user_id: str,
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
) -> str:
    """Run one tool for Pi long-run mode with MCP context and Haystack-style guards."""
    from src.agent_profile import profile_manager
    from src.runtime.pi_runtime.tool_manifest import get_session_tool_registry

    profile = profile_manager.get_profile(profile_name)
    args = dict(arguments or {})

    await _ensure_mcp_session_context(session_id, profile_name, user_id)

    from src.runtime.context import bind_session_id

    with bind_session_id(session_id):
        entry = get_session_tool_registry(session_id).get(tool_name)
        if entry and entry.source == "mcp":
            server = entry.server_name or await _resolve_mcp_server(
                session_id, profile, tool_name
            )
            if not server:
                raise RuntimeError(f"No MCP server for tool {tool_name}")
            return await _invoke_mcp_tool(
                session_id=session_id,
                profile_name=profile_name,
                user_id=user_id,
                server_name=server,
                tool_name=tool_name,
                arguments=args,
            )

        return await _invoke_native_tool(
            session_id=session_id,
            profile=profile,
            profile_name=profile_name,
            user_id=user_id,
            tool_name=tool_name,
            arguments=args,
        )

"""Resident tools vs groups loaded on demand.

The first model call sees a small tool set. ``activate_tool_group`` attaches
the rest to the running Haystack agent before the next step.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from haystack.tools import Tool

logger = logging.getLogger("aion.tool_exposure")

# MCP servers whose tools may appear on the first turn.
RESIDENT_MCP_SERVERS = frozenset({"skills_hub", "session_sandbox"})

# Full JSON schema on the first turn. Everything else in those servers waits.
RESIDENT_TOOL_NAMES = frozenset(
    {
        "skill_search",
        "skill_view",
        "skill_list",
        "sandbox_list_files",
        "sandbox_read_text_file",
        "sandbox_write_workspace_file",
        "sandbox_grep_content",
        "sandbox_read_file_chunk",
        "memory_recall",
        "memory_note",
        "memory_forget",
        "sql_memory_search",
    }
)

# Native bundles kept as real tools (small). Others are a one-line manifest.
RESIDENT_NATIVE_GROUPS = frozenset({"mnemos"})


def _run_on_agent_loop(coro: Any) -> str:
    """Haystack tools are sync. Schedule the coroutine on the API loop."""
    import asyncio

    try:
        from src.main import _GLOBAL_LOOP
    except Exception:
        _GLOBAL_LOOP = None
    loop = _GLOBAL_LOOP
    if loop is not None and loop.is_running():
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=float(os.getenv("AION_TOOL_GROUP_ACTIVATE_TIMEOUT_SEC", "90")))
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is not None and running.is_running():
        raise RuntimeError("activate_tool_group cannot run inside the API event loop")
    return asyncio.run(coro)


def defer_tool_groups_enabled() -> bool:
    return os.getenv("AION_DEFER_TOOL_GROUPS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def resident_mcp_servers(server_names: Sequence[str]) -> List[str]:
    names = [n for n in server_names if n]
    if not defer_tool_groups_enabled():
        return list(names)
    return [n for n in names if n in RESIDENT_MCP_SERVERS]


def deferred_mcp_servers(server_names: Sequence[str]) -> List[str]:
    names = [n for n in server_names if n]
    if not defer_tool_groups_enabled():
        return []
    return [n for n in names if n not in RESIDENT_MCP_SERVERS]


def deferred_native_groups(groups: Sequence[str]) -> List[str]:
    if not defer_tool_groups_enabled():
        return []
    return [g for g in groups if g and g not in RESIDENT_NATIVE_GROUPS]


def select_resident_tools(tools: Sequence[Any]) -> List[Any]:
    """Drop heavy tools when deferral is on. Built-ins that are not in the
    resident name set stay if they are not native web/research tools."""
    if not defer_tool_groups_enabled():
        return list(tools)
    deferred_native = _deferred_native_tool_names()
    kept: List[Any] = []
    for tool in tools:
        name = getattr(tool, "name", None) or ""
        if name in deferred_native:
            continue
        if _looks_like_resident_mcp_tool(name) and name not in RESIDENT_TOOL_NAMES:
            continue
        kept.append(tool)
    return kept


def _deferred_native_tool_names() -> set[str]:
    from src.runtime.native_tools.registry_io import get_bundle

    names: set[str] = set()
    # Known heavy bundles. Unknown bundles are not stripped here.
    for gid in ("web_research", "deep_research"):
        bundle = get_bundle(gid) or {}
        for tid in bundle.get("tools") or []:
            names.add(str(tid))
    return names


def _looks_like_resident_mcp_tool(name: str) -> bool:
    return name.startswith("sandbox_") or name.startswith("skill_")


def activatable_groups(profile: Any) -> List[str]:
    """Groups the model can pass to activate_tool_group."""
    groups = deferred_mcp_servers(getattr(profile, "mcp_servers", None) or [])
    groups.extend(
        deferred_native_groups(getattr(profile, "native_tool_groups", None) or [])
    )
    if defer_tool_groups_enabled():
        present = set(getattr(profile, "mcp_servers", None) or [])
        for name in ("session_sandbox", "skills_hub"):
            if name in present and name not in groups:
                groups.append(name)
    return groups


def deferred_prompt_section(profile: Any) -> str:
    if not defer_tool_groups_enabled():
        return ""
    lines: List[str] = [
        "\n## Tool groups on demand",
        "Only a small tool set is loaded. Before using any other group, call "
        "`activate_tool_group` with its name. The next step can call those tools.",
    ]
    partial = {
        "session_sandbox": "remaining workspace tools (Python, patches, search)",
        "skills_hub": "remaining skill tools, including save when write is enabled",
    }
    servers = activatable_groups(profile)
    native = set(
        deferred_native_groups(getattr(profile, "native_tool_groups", None) or [])
    )
    try:
        from src.mcp_manager import mcp_manager

        for name in servers:
            if name in native:
                lines.append(f"- `{name}`: native tools for this profile")
                continue
            if name in partial:
                lines.append(f"- `{name}`: {partial[name]}")
                continue
            cfg = mcp_manager.get_server_config(name) or {}
            desc = (cfg.get("description") or "MCP tools").strip().split("\n")[0]
            lines.append(f"- `{name}`: {desc}")
    except Exception:
        for name in servers:
            lines.append(f"- `{name}`")
    if len(lines) <= 2:
        return ""
    return "\n".join(lines)


def make_activate_tool_group_tool(
    *,
    session_id: str,
    user_id: str,
    tenant_id: str,
    profile: Any,
) -> Tool:
    allowed = set(activatable_groups(profile))

    def activate_tool_group(group: str) -> str:
        gid = (group or "").strip()
        if not gid:
            return "Error: group name required. Available: " + ", ".join(sorted(allowed))
        if gid not in allowed:
            return (
                f"Error: group '{gid}' is not on this profile. "
                f"Available: {', '.join(sorted(allowed)) or '(none)'}."
            )

        async def _activate() -> str:
            if gid in deferred_native_groups(
                getattr(profile, "native_tool_groups", None) or []
            ):
                tools = _native_group_tools(gid, session_id, user_id, profile)
            else:
                tools = await _mcp_group_tools(
                    gid, session_id, user_id, tenant_id, profile
                )
            if not tools:
                return f"Error: group '{gid}' produced no tools."
            attached = publish_tools(tools, session_id=session_id)
            names = ", ".join(getattr(t, "name", "") for t in attached)
            return f"Activated group '{gid}'. Tools now available: {names}."

        return _run_on_agent_loop(_activate())

    return Tool(
        name="activate_tool_group",
        description=(
            "Load the full tool schemas for one deferred group "
            "(an MCP server slug or a native bundle such as web_research). "
            "Call this before using tools from that group."
        ),
        parameters={
            "type": "object",
            "properties": {
                "group": {
                    "type": "string",
                    "description": "Group name from the system prompt manifest.",
                }
            },
            "required": ["group"],
        },
        function=activate_tool_group,
    )


def _native_group_tools(
    group: str, session_id: str, user_id: str, profile: Any
) -> List[Tool]:
    from src.runtime.native_tools.factory_table import NATIVE_TOOL_FACTORIES
    from src.runtime.native_tools.registry_io import get_bundle

    bundle = get_bundle(group) or {}
    tools: List[Tool] = []
    for tid in bundle.get("tools") or []:
        factory = NATIVE_TOOL_FACTORIES.get(str(tid))
        if not factory:
            continue
        try:
            tools.append(factory(session_id, user_id, profile))
        except ValueError as exc:
            logger.debug("activate native %s skipped: %s", tid, exc)
    return tools


async def _mcp_group_tools(
    server_name: str,
    session_id: str,
    user_id: str,
    tenant_id: str,
    profile: Any,
) -> List[Tool]:
    from src.main import build_mcp_tools
    from src.mcp_manager import mcp_manager

    cfg = mcp_manager.get_server_config(server_name)
    if not cfg:
        logger.warning("activate_tool_group: server %s missing from registry", server_name)
        return []
    await mcp_manager.warm_session(
        session_id,
        [server_name],
        profile_slug=getattr(profile, "slug", "") or "generic_assistant",
        user_id=user_id,
        tenant_id=tenant_id,
    )
    built = await build_mcp_tools(
        server_name, cfg, session_id, user_id=user_id
    )
    return list(built or [])


def publish_tools(extra: Iterable[Any], *, session_id: str = "") -> List[Any]:
    """Append tools to the live agent and to the current Haystack execution inputs.

    The tool runs on the API loop. The execution context lives on the agent
    thread, so it is read from the turn registry, not from a ContextVar.
    """
    from src.runtime.turn_compaction import _agent_exec_ctx, resolve_turn_runtime

    attached: List[Any] = []
    rt = resolve_turn_runtime(session_id or None)
    agent = rt.get("agent") if isinstance(rt, dict) else None
    current: List[Any] = list(getattr(agent, "tools", None) or []) if agent else []
    names = {getattr(t, "name", None) for t in current}
    for tool in extra:
        name = getattr(tool, "name", None)
        if not name or name in names:
            continue
        current.append(tool)
        names.add(name)
        attached.append(tool)
    if agent is not None:
        agent.tools = current
    exec_ctx = rt.get("agent_exec_ctx") if isinstance(rt, dict) else None
    if exec_ctx is None and _agent_exec_ctx is not None:
        exec_ctx = _agent_exec_ctx.get()
    if exec_ctx is not None and current:
        gen_inputs = getattr(exec_ctx, "chat_generator_inputs", None)
        if isinstance(gen_inputs, dict):
            gen_inputs["tools"] = current
        inv_inputs = getattr(exec_ctx, "tool_invoker_inputs", None)
        if isinstance(inv_inputs, dict):
            inv_inputs["tools"] = current
    return attached

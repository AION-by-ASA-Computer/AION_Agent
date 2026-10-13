"""Resident tools vs tools loaded by name.

The first model call sees schemas for tools used every session. Everything
else stays as a name until ``tool_search`` publishes the schema on the live
Haystack run. ``activate_tool_group`` remains the internal loader for one
MCP server or native bundle.
"""

from __future__ import annotations

import logging
import os
import re
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
        "sandbox_edit_workspace_file",
        "sandbox_grep_content",
        "sandbox_read_file_chunk",
        "sandbox_run_python_file",
        "sandbox_install_python_packages",
        "sandbox_run_node_file",
        "sandbox_install_npm_packages",
        "memory_recall",
        "memory_note",
        "memory_forget",
        "sql_memory_search",
    }
)

# Native bundles kept as real tools (small). Others are a one-line manifest.
RESIDENT_NATIVE_GROUPS = frozenset({"mnemos"})

# Cold-server tools named by skills. The slug is warmed only when tool_search
# asks for that name and the server is on the profile.
_KNOWN_COLD_TOOLS = {
    "render_chart": "charts",
    "doc_ingest": "ocr",
    "ocr_file": "ocr",
    "pdf_evidence_crop": "ocr",
    "geocode_place": "geocoding",
    "reverse_geocode": "geocoding",
    "session_search": "query_memory",
    "search_known_sql": "query_memory",
    "search_known_query": "query_memory",
    "save_successful_sql": "query_memory",
    "save_successful_query": "query_memory",
    "list_saved_sql": "query_memory",
    "list_sql_projects": "query_memory",
}

_SEARCH_LIMIT = 5
_DEFERRED_BY_SESSION: Dict[str, List[Any]] = {}


def _run_on_agent_loop(coro: Any) -> Any:
    """Haystack tools are sync. Schedule the coroutine on the API loop."""
    import asyncio

    try:
        from src.main import _GLOBAL_LOOP
    except Exception:
        _GLOBAL_LOOP = None
    loop = _GLOBAL_LOOP
    if loop is not None and loop.is_running():
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(
            timeout=float(os.getenv("AION_TOOL_GROUP_ACTIVATE_TIMEOUT_SEC", "90"))
        )
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


def _is_deferred_tool(name: str, deferred_native: set[str]) -> bool:
    if name in deferred_native:
        return True
    return _looks_like_resident_mcp_tool(name) and name not in RESIDENT_TOOL_NAMES


def partition_resident_tools(tools: Sequence[Any]) -> Tuple[List[Any], List[Any]]:
    """Split a discovered tool list into (loaded schemas, deferred pool)."""
    if not defer_tool_groups_enabled():
        return list(tools), []
    deferred_native = _deferred_native_tool_names()
    kept: List[Any] = []
    deferred: List[Any] = []
    for tool in tools:
        name = getattr(tool, "name", None) or ""
        if _is_deferred_tool(name, deferred_native):
            deferred.append(tool)
        else:
            kept.append(tool)
    return kept, deferred


def select_resident_tools(tools: Sequence[Any]) -> List[Any]:
    """Drop heavy tools when deferral is on. Built-ins that are not in the
    resident name set stay if they are not native web/research tools."""
    kept, _deferred = partition_resident_tools(tools)
    return kept


def remember_deferred_tools(session_id: str, tools: Sequence[Any]) -> None:
    """Keep deferred tool objects for this chat so tool_search can publish them."""
    sid = session_id or ""
    current = _DEFERRED_BY_SESSION.get(sid, [])
    merged, _added = _extend_tool_collection(current, tools)
    _DEFERRED_BY_SESSION[sid] = merged


def deferred_tools_for(session_id: str) -> List[Any]:
    return list(_DEFERRED_BY_SESSION.get(session_id or "", []))


def clear_deferred_tools(session_id: str = "") -> None:
    if session_id:
        _DEFERRED_BY_SESSION.pop(session_id, None)
    else:
        _DEFERRED_BY_SESSION.clear()


def attach_deferred_pool(agent: Any, tools: Sequence[Any]) -> None:
    """Stash deferred tools on the cached agent as well as the session map."""
    if agent is None:
        return
    existing = list(getattr(agent, "_aion_deferred_tools", None) or [])
    merged, _added = _extend_tool_collection(existing, tools)
    agent._aion_deferred_tools = merged


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
        "\n## Tools on demand",
        "Some tools are already loaded with a full schema. If a skill names a tool "
        "that is not in your tool list, call `tool_search` once with that exact name. "
        "The next step can call it. Do not invent a workaround when the name is missing.",
    ]
    partial = {
        "session_sandbox": (
            "deferred workspace tools such as sandbox_exec_allowlisted, "
            "sandbox_apply_patch, sandbox_fnmatch_glob"
        ),
        "skills_hub": "deferred skill tools, including save when write is enabled",
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


def _norm_query(text: str) -> str:
    return re.sub(r"[_\W]+", " ", (text or "").lower()).strip()


def _tool_search_blob(tool: Any) -> str:
    name = _tool_name(tool)
    desc = str(getattr(tool, "description", None) or "")
    params = getattr(tool, "parameters", None) or {}
    props: List[str] = []
    if isinstance(params, dict):
        raw = params.get("properties") or {}
        if isinstance(raw, dict):
            props = [str(key) for key in raw.keys()]
    return _norm_query(" ".join([name, desc, " ".join(props)]))


def rank_tools(query: str, tools: Sequence[Any]) -> List[Any]:
    """Score tools by name, description, and parameter names. Cap at 5."""
    q = (query or "").strip()
    qn = _norm_query(q)
    if not qn:
        return []
    scored: List[Tuple[int, str, Any]] = []
    for tool in tools:
        name = _tool_name(tool)
        if not name:
            continue
        blob = _tool_search_blob(tool)
        name_n = _norm_query(name)
        if qn == name_n or q.lower() == name.lower():
            score = 100
        elif qn in name_n or name_n in qn:
            score = 80
        else:
            tokens = [tok for tok in qn.split() if len(tok) > 2]
            hits = sum(1 for tok in tokens if tok in blob)
            score = hits * 10 if hits and hits == len(tokens) else 0
        if score:
            scored.append((score, name, tool))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [tool for _score, _name, tool in scored[:_SEARCH_LIMIT]]


def format_deferred_catalog(tools: Sequence[Any]) -> str:
    """One line per deferred tool: name plus the first sentence of the description."""
    rows: List[str] = []
    for tool in tools:
        name = _tool_name(tool)
        if not name:
            continue
        desc = str(getattr(tool, "description", None) or "").strip().split("\n")[0]
        if len(desc) > 140:
            desc = desc[:137] + "..."
        rows.append(f"- `{name}`: {desc}" if desc else f"- `{name}`")
    if not rows:
        return ""
    return "\n".join(
        [
            "\n## Deferred tool names",
            "These tools are not loaded yet. Call `tool_search` with the exact name. "
            "The next step can call the tool.",
            *rows,
        ]
    )


def _already_loaded_names(session_id: str) -> set[str]:
    from src.runtime.turn_compaction import _agent_exec_ctx, resolve_turn_runtime

    names: set[str] = set()
    rt = resolve_turn_runtime(session_id or None)
    agent = rt.get("agent") if isinstance(rt, dict) else None
    exec_ctx = rt.get("agent_exec_ctx") if isinstance(rt, dict) else None
    if exec_ctx is None and _agent_exec_ctx is not None:
        exec_ctx = _agent_exec_ctx.get()
    for source in (
        getattr(agent, "tools", None) if agent is not None else None,
        getattr(exec_ctx, "tools", None) if exec_ctx is not None else None,
    ):
        for tool in _as_tool_list(source):
            name = _tool_name(tool)
            if name and name != "tool_search":
                names.add(name)
    return names


def _pool_for(session_id: str) -> List[Any]:
    from src.runtime.turn_compaction import resolve_turn_runtime

    rt = resolve_turn_runtime(session_id or None)
    agent = rt.get("agent") if isinstance(rt, dict) else None
    agent_tools = (
        list(getattr(agent, "_aion_deferred_tools", None) or [])
        if agent is not None
        else []
    )
    merged, _added = _extend_tool_collection(
        agent_tools, deferred_tools_for(session_id)
    )
    return merged


def _group_for_query(query: str, profile: Any) -> Optional[str]:
    q = (query or "").strip()
    if not q:
        return None
    groups = activatable_groups(profile)
    qn = _norm_query(q)
    for name in groups:
        if name.lower() == q.lower() or _norm_query(name) == qn:
            return name
    server = _KNOWN_COLD_TOOLS.get(q) or _KNOWN_COLD_TOOLS.get(q.lower())
    if server and server in groups:
        return server
    if len(qn) < 4:
        return None
    try:
        from src.mcp_manager import mcp_manager
    except Exception:
        return None
    hits: List[str] = []
    for name in groups:
        cfg = mcp_manager.get_server_config(name) or {}
        desc = _norm_query(str(cfg.get("description") or ""))
        if qn in desc or qn in _norm_query(name):
            hits.append(name)
    if len(hits) == 1:
        return hits[0]
    return None


def _remember_loaded(session_id: str, tools: Sequence[Any]) -> None:
    remember_deferred_tools(session_id, tools)
    from src.runtime.turn_compaction import resolve_turn_runtime

    rt = resolve_turn_runtime(session_id or None)
    agent = rt.get("agent") if isinstance(rt, dict) else None
    if agent is not None:
        attach_deferred_pool(agent, tools)


def _load_group_tools(
    group: str,
    *,
    session_id: str,
    user_id: str,
    tenant_id: str,
    profile: Any,
) -> List[Any]:
    if group in deferred_native_groups(
        getattr(profile, "native_tool_groups", None) or []
    ):
        return _native_group_tools(group, session_id, user_id, profile)

    async def _activate() -> List[Any]:
        return await _mcp_group_tools(group, session_id, user_id, tenant_id, profile)

    loaded = _run_on_agent_loop(_activate())
    return list(loaded or [])


def make_tool_search_tool(
    *,
    session_id: str,
    user_id: str,
    tenant_id: str,
    profile: Any,
) -> Tool:
    def tool_search(query: str) -> str:
        q = (query or "").strip()
        pool = _pool_for(session_id)
        catalog = sorted({_tool_name(t) for t in pool if _tool_name(t)})
        groups = activatable_groups(profile)
        available = (
            ", ".join(catalog + [g for g in groups if g not in catalog]) or "(none)"
        )
        if not q:
            return "Error: query required. Available: " + available

        already = _already_loaded_names(session_id)
        if q in already or _norm_query(q) in {_norm_query(n) for n in already}:
            return f"'{q}' is already loaded. Call it directly."

        matches = rank_tools(q, pool)
        top = matches[0] if matches else None
        strong = bool(top) and (
            _tool_name(top).lower() == q.lower()
            or _norm_query(_tool_name(top)) == _norm_query(q)
        )
        if strong:
            chosen = [
                t for t in matches if _norm_query(_tool_name(t)) == _norm_query(q)
            ] or matches
        else:
            group = _group_for_query(q, profile)
            if group:
                loaded = _load_group_tools(
                    group,
                    session_id=session_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    profile=profile,
                )
                if loaded:
                    _remember_loaded(session_id, loaded)
                ranked = rank_tools(q, loaded)
                if _norm_query(q) == _norm_query(group) or not ranked:
                    chosen = list(loaded[:_SEARCH_LIMIT])
                else:
                    chosen = ranked
            elif matches:
                chosen = matches
            else:
                return (
                    f"No tool matched '{q}'. Call tool_search with an exact name. "
                    f"Available: {available}."
                )
        if not chosen:
            return (
                f"No tool matched '{q}'. Call tool_search with an exact name. "
                f"Available: {available}."
            )
        attached = publish_tools(chosen[:_SEARCH_LIMIT], session_id=session_id)
        names = ", ".join(_tool_name(t) for t in attached if _tool_name(t))
        return (
            f"Loaded {len(attached)} tool(s): {names}. "
            "You can call them on the next step."
        )

    return Tool(
        name="tool_search",
        description=(
            "Load the schema for a tool that is not in the current tool list. "
            "Pass the exact tool name from a skill or from the deferred-name catalog "
            "(for example sandbox_exec_allowlisted, render_chart, web_search, ocr). "
            "The next step can call the loaded tools. Do not use this for tools "
            "that already have a schema."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Exact tool name or MCP server slug to load.",
                }
            },
            "required": ["query"],
        },
        function=tool_search,
    )


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
            return "Error: group name required. Available: " + ", ".join(
                sorted(allowed)
            )
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
        logger.warning(
            "activate_tool_group: server %s missing from registry", server_name
        )
        return []
    await mcp_manager.warm_session(
        session_id,
        [server_name],
        profile_slug=getattr(profile, "slug", "") or "generic_assistant",
        user_id=user_id,
        tenant_id=tenant_id,
    )
    built = await build_mcp_tools(server_name, cfg, session_id, user_id=user_id)
    return list(built or [])


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", None) or "")


def _as_tool_list(tools: Any) -> List[Any]:
    if tools is None:
        return []
    if isinstance(tools, list):
        return list(tools)
    try:
        return list(tools)
    except TypeError:
        return [tools]


def _extend_tool_collection(
    existing: Any, extra: Sequence[Any]
) -> Tuple[Any, List[Any]]:
    """Append named tools that are not already present. Returns (collection, added)."""
    current = _as_tool_list(existing)
    names = {_tool_name(t) for t in current if _tool_name(t)}
    added: List[Any] = []
    for tool in extra:
        name = _tool_name(tool)
        if not name or name in names:
            continue
        current.append(tool)
        names.add(name)
        added.append(tool)
    return current, added


def publish_tools(extra: Iterable[Any], *, session_id: str = "") -> List[Any]:
    """Append tools to the cached agent and to the live Haystack run.

    Haystack 2.x re-reads ``exe_context.tools`` on every step and injects that
    snapshot into the chat generator and the tool executor. Writing only
    ``agent.tools`` or ``chat_generator_inputs["tools"]`` leaves the current
    turn on the resident set, so ``activate_tool_group`` looks successful
    while ``clickup_*`` / Outlook tools stay ``not found``.
    """
    from src.runtime.turn_compaction import _agent_exec_ctx, resolve_turn_runtime

    incoming = [t for t in extra if _tool_name(t)]
    if not incoming:
        return []

    rt = resolve_turn_runtime(session_id or None)
    agent = rt.get("agent") if isinstance(rt, dict) else None
    exec_ctx = rt.get("agent_exec_ctx") if isinstance(rt, dict) else None
    if exec_ctx is None and _agent_exec_ctx is not None:
        exec_ctx = _agent_exec_ctx.get()

    if agent is not None:
        agent.tools, _ = _extend_tool_collection(
            getattr(agent, "tools", None), incoming
        )

    live_added: List[Any] = incoming
    if exec_ctx is not None:
        live, live_added = _extend_tool_collection(
            getattr(exec_ctx, "tools", None), incoming
        )
        exec_ctx.tools = live
        state = getattr(exec_ctx, "state", None)
        if state is not None and hasattr(state, "set"):
            try:
                state.set("tools", _as_tool_list(live))
            except Exception:
                logger.debug(
                    "publish_tools: could not write state.tools", exc_info=True
                )
        # Haystack injects tools from exe_context.tools each step; keep these
        # in sync for older snapshots / tests that still read the dicts.
        for attr in (
            "chat_generator_inputs",
            "tool_execution_inputs",
            "tool_invoker_inputs",
        ):
            payload = getattr(exec_ctx, attr, None)
            if isinstance(payload, dict):
                payload["tools"] = live

    return live_added or incoming

"""Factory registrate per tool nativi (id logico → costruttore Haystack Tool)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable, Dict, Optional

from haystack.tools import Tool

if TYPE_CHECKING:
    from src.agent_profile import AgentProfile

from src.runtime.context import get_current_session_id
from src.runtime.native_tool_events import (
    emit_tool_end,
    emit_tool_error,
    emit_tool_start,
)
from src.runtime.turn_compaction import maybe_compact_after_tool
from src.runtime.web_search_context import get_web_search_request_context

from .web_providers import run_web_fetch_page, run_web_search

NativeToolBuilder = Callable[..., Tool]


class WebSearchExecutor:
    def __call__(
        self,
        query: str,
        max_results: int | None = None,
        language: str | None = None,
    ) -> str:
        sid = get_current_session_id()
        inp = {"query": query, "max_results": max_results, "language": language}
        call_id = emit_tool_start(sid, "web_search", inp)
        try:
            if not get_web_search_request_context().enabled:
                out = json.dumps(
                    {
                        "error": "web_search_disabled_by_user",
                        "message": "Web search disabled for this message.",
                        "results": [],
                    },
                    ensure_ascii=False,
                )
            else:
                out = run_web_search(query, max_results=max_results, language=language)
        except Exception as e:
            emit_tool_error(sid, "web_search", call_id, str(e))
            raise
        out = maybe_compact_after_tool(tool_name="web_search", result=out)
        emit_tool_end(sid, "web_search", call_id, out)
        return out


class WebFetchPageExecutor:
    def __call__(self, url: str, prefer_stealth: bool = False) -> str:
        sid = get_current_session_id()
        inp = {"url": url, "prefer_stealth": prefer_stealth}
        call_id = emit_tool_start(sid, "web_fetch_page", inp)
        try:
            if not get_web_search_request_context().enabled:
                out = json.dumps(
                    {
                        "error": "web_search_disabled_by_user",
                        "message": "Page download disabled together with web search.",
                        "url": url,
                        "text": "",
                    },
                    ensure_ascii=False,
                )
            else:
                out = run_web_fetch_page(url, prefer_stealth=prefer_stealth)
        except Exception as e:
            emit_tool_error(sid, "web_fetch_page", call_id, str(e))
            raise
        out = maybe_compact_after_tool(tool_name="web_fetch_page", result=out)
        emit_tool_end(sid, "web_fetch_page", call_id, out)
        return out


def _profile_slug(profile: Optional["AgentProfile"]) -> str:
    if profile is None:
        return "default"
    return str(getattr(profile, "slug", None) or getattr(profile, "name", "default"))


def build_web_search_tool(
    session_id: str, user_id: str, profile: Optional["AgentProfile"] = None
) -> Tool:
    _ = session_id, user_id, profile
    return Tool(
        name="web_search",
        description=(
            "Web search (Tavily / Brave / SearXNG) in base alla configurazione server. "
            "Returns JSON with results[{title,url,snippet,provider}]. Use concise queries."
        ),
        function=WebSearchExecutor(),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {
                    "type": "integer",
                    "description": "Max results (1–20, default da env)",
                },
                "language": {
                    "type": "string",
                    "description": "Optional language code (es. it, en)",
                },
            },
            "required": ["query"],
        },
    )


def build_web_fetch_page_tool(
    session_id: str, user_id: str, profile: Optional["AgentProfile"] = None
) -> Tool:
    _ = session_id, user_id, profile
    return Tool(
        name="web_fetch_page",
        description=(
            "Scarica il contenuto testuale di una singola pagina HTTP(S). "
            "Prefer URLs already obtained from web_search. Returns JSON with a text field."
        ),
        function=WebFetchPageExecutor(),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL completo https://..."},
                "prefer_stealth": {
                    "type": "boolean",
                    "description": "Se true e AION_SCRAPLING_STEALTH_ENABLED=1, tenta browser stealth (lento)",
                },
            },
            "required": ["url"],
        },
    )


def _build_sql_memory_tool(
    tool_id: str,
    session_id: str,
    user_id: str,
    profile: Optional["AgentProfile"] = None,
) -> Tool:
    from src.runtime.sql_query_memory_tools import build_sql_query_memory_haystack_tools

    slug = _profile_slug(profile)
    for t in build_sql_query_memory_haystack_tools(session_id, user_id, slug):
        if getattr(t, "name", None) == tool_id:
            return t
    raise ValueError(
        f"SQL QueryMemory tool {tool_id!r} not built (disabled or profile mismatch)"
    )


def build_sql_memory_search_tool(
    session_id: str, user_id: str, profile: Optional["AgentProfile"] = None
) -> Tool:
    return _build_sql_memory_tool("sql_memory_search", session_id, user_id, profile)


def build_sql_memory_save_tool(
    session_id: str, user_id: str, profile: Optional["AgentProfile"] = None
) -> Tool:
    return _build_sql_memory_tool("sql_memory_save", session_id, user_id, profile)


def build_sql_memory_update_tool(
    session_id: str, user_id: str, profile: Optional["AgentProfile"] = None
) -> Tool:
    return _build_sql_memory_tool("sql_memory_update", session_id, user_id, profile)


def build_sql_memory_delete_tool(
    session_id: str, user_id: str, profile: Optional["AgentProfile"] = None
) -> Tool:
    return _build_sql_memory_tool("sql_memory_delete", session_id, user_id, profile)


def build_sql_memory_list_projects_tool(
    session_id: str, user_id: str, profile: Optional["AgentProfile"] = None
) -> Tool:
    return _build_sql_memory_tool(
        "sql_memory_list_projects", session_id, user_id, profile
    )


def build_sql_memory_list_saved_tool(
    session_id: str, user_id: str, profile: Optional["AgentProfile"] = None
) -> Tool:
    return _build_sql_memory_tool("sql_memory_list_saved", session_id, user_id, profile)


def build_trigger_research_tool(
    session_id: str, user_id: str, profile: Optional["AgentProfile"] = None
) -> Tool:
    _ = profile
    from src.research.handler import deep_research_enabled

    if not deep_research_enabled():
        raise ValueError("trigger_research disabled (AION_DEEP_RESEARCH_ENABLED=0)")

    owner_id = (user_id or "default").strip() or "default"

    def trigger_fn(
        topic: str,
        max_rounds: int | None = None,
        max_time: int | None = None,
        category: str | None = None,
    ) -> str:
        sid = session_id or get_current_session_id()
        inp: dict = {"topic": topic}
        if max_rounds is not None:
            inp["max_rounds"] = max_rounds
        if max_time is not None:
            inp["max_time"] = max_time
        if category:
            inp["category"] = category
        call_id = emit_tool_start(sid, "trigger_research", inp)
        try:
            from src.runtime.native_tools.research_tools import run_trigger_research

            out = run_trigger_research(
                json.dumps(inp), session_id=sid, user_id=owner_id
            )
        except Exception as e:
            emit_tool_error(sid, "trigger_research", call_id, str(e))
            raise
        emit_tool_end(sid, "trigger_research", call_id, out)
        return out

    return Tool(
        name="trigger_research",
        description=(
            "Start a deep research job on any topic — streams progress and produces a detailed "
            "HTML report with export-to-PDF. Use for 'research X', 'deep research on Y', "
            "'investigate Z'. NOT for quick facts (use web_search in normal mode)."
        ),
        function=trigger_fn,
        parameters={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Research question or topic",
                },
                "max_rounds": {
                    "type": "integer",
                    "description": "Optional max search rounds (0=auto)",
                },
                "max_time": {
                    "type": "integer",
                    "description": "Optional max seconds (60-1800)",
                },
                "category": {
                    "type": "string",
                    "description": "Optional: product, comparison, howto, factcheck",
                },
            },
            "required": ["topic"],
        },
    )


def build_manage_research_tool(
    session_id: str, user_id: str, profile: Optional["AgentProfile"] = None
) -> Tool:
    _ = session_id, profile
    from src.research.handler import deep_research_enabled

    if not deep_research_enabled():
        raise ValueError("manage_research disabled (AION_DEEP_RESEARCH_ENABLED=0)")

    owner_id = (user_id or "default").strip() or "default"

    def manage_fn(
        action: str = "list", id: str | None = None, search: str | None = None
    ) -> str:
        sid = get_current_session_id()
        inp = {"action": action}
        if id:
            inp["id"] = id
        if search:
            inp["search"] = search
        call_id = emit_tool_start(sid, "manage_research", inp)
        try:
            from src.runtime.native_tools.research_tools import run_manage_research

            out = run_manage_research(json.dumps(inp), user_id=owner_id)
        except Exception as e:
            emit_tool_error(sid, "manage_research", call_id, str(e))
            raise
        emit_tool_end(sid, "manage_research", call_id, out)
        return out

    return Tool(
        name="manage_research",
        description=(
            "List, read, or delete saved deep research reports. "
            "action=list|read|delete; id required for read/delete."
        ),
        function=manage_fn,
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "read", "delete"]},
                "id": {"type": "string", "description": "Research session id"},
                "search": {
                    "type": "string",
                    "description": "Filter library by query text",
                },
            },
            "required": ["action"],
        },
    )


NATIVE_TOOL_FACTORIES: Dict[str, NativeToolBuilder] = {
    "web_search": build_web_search_tool,
    "web_fetch_page": build_web_fetch_page_tool,
    "sql_memory_search": build_sql_memory_search_tool,
    "sql_memory_save": build_sql_memory_save_tool,
    "sql_memory_update": build_sql_memory_update_tool,
    "sql_memory_delete": build_sql_memory_delete_tool,
    "sql_memory_list_projects": build_sql_memory_list_projects_tool,
    "sql_memory_list_saved": build_sql_memory_list_saved_tool,
    "trigger_research": build_trigger_research_tool,
    "manage_research": build_manage_research_tool,
}

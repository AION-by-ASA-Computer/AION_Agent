"""Block schema exploration when server injected a high-confidence SQL cache for this turn."""

from __future__ import annotations

import os
import re
from typing import Mapping, Optional, Tuple

from src.runtime.sql_query_memory_context import get_sql_qm_turn_context

_EXPLORATION_TOOL_SUFFIXES = frozenset(
    {
        "list_tables",
        "list_schemas",
        "search_known_sql",
        "sql_memory_search",
        "mempalace_search",
        "mempalace_list_drawers",
    }
)

_SQL_EXEC_SUFFIXES = frozenset(
    {"execute_sql", "query", "run_sql", "sql_query", "mysql_query", "postgres_query"}
)

# Only qualified names after FROM/JOIN (avoid treating aliases dm./u./d. as schemas).
_FROM_JOIN_SCHEMA_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*)",
    re.IGNORECASE,
)


def gate_enabled() -> bool:
    return os.getenv("AION_SQL_QM_GATE_EXPLORATION", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def extract_schemas_from_sql_text(sql_text: str) -> Tuple[str, ...]:
    found: list[str] = []
    for m in _FROM_JOIN_SCHEMA_RE.finditer(sql_text or ""):
        sch = m.group(1)
        if sch not in found:
            found.append(sch)
    return tuple(found[:6])


def _tool_base_name(tool_name: str) -> str:
    return (tool_name or "").split("-")[-1].strip().lower()


def _is_exploration_tool(tool_name: str) -> bool:
    base = _tool_base_name(tool_name)
    return base in _EXPLORATION_TOOL_SUFFIXES


def _is_sql_exec_tool(tool_name: str) -> bool:
    base = _tool_base_name(tool_name)
    return base in _SQL_EXEC_SUFFIXES


def _exploration_gate_active(ctx) -> bool:
    if not ctx.sql_cache_inject_active:
        return False
    if ctx.execute_sql_succeeded or ctx.exploration_unlocked:
        return False
    return True


def block_exploration_tool_if_sql_cache(
    server_name: str,
    tool_name: str,
    session_id: str,
    tool_kwargs: Optional[Mapping[str, object]] = None,
) -> Optional[str]:
    """
    When pre-turn QueryMemory injected SQL, block list_tables / memory search
    until execute_sql succeeds, or after a failed attempt (exploration_unlocked).
    """
    _ = tool_kwargs
    if not gate_enabled():
        return None
    ctx = get_sql_qm_turn_context(session_id)
    if ctx is None or ctx.session_id != session_id:
        return None
    if not _exploration_gate_active(ctx):
        return None
    if not _is_exploration_tool(tool_name):
        return None
    schemas = (
        ", ".join(ctx.sql_cache_schemas)
        if ctx.sql_cache_schemas
        else "(see injected SQL)"
    )
    return (
        f"Blocked `{server_name}/{tool_name}`: this turn already has a server-side "
        f"QueryMemory SQL cache. Run `execute_sql` with the injected query first "
        f"(schemas: {schemas}). If that fails, fix table names or bind values, then "
        f"you may search memory or list tables."
    )


def mark_sql_exec_tool_used(session_id: str, tool_name: str) -> None:
    if not _is_sql_exec_tool(tool_name):
        return
    from src.runtime.sql_query_memory_context import mark_execute_sql_succeeded

    mark_execute_sql_succeeded(session_id)


def mark_sql_exec_tool_failed(session_id: str, tool_name: str) -> None:
    if not _is_sql_exec_tool(tool_name):
        return
    from src.runtime.sql_query_memory_context import mark_execute_sql_failed

    mark_execute_sql_failed(session_id)


def mark_execute_sql_used(session_id: str, tool_name: str) -> None:
    mark_sql_exec_tool_used(session_id, tool_name)

"""PostgreSQL MCP query timeouts (toolbox-postgres)."""

from __future__ import annotations

import os

_POSTGRES_SERVER = "toolbox-postgres"
_QUERY_TOOLS = frozenset({"query"})


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def is_postgres_query_tool(server_name: str, tool_name: str) -> bool:
    base = (tool_name or "").split("-")[-1]
    return (server_name or "").strip() == _POSTGRES_SERVER and base in _QUERY_TOOLS


def postgres_query_timeout_sec(server_name: str, tool_name: str) -> float | None:
    """Per-tool asyncio timeout; None = no extra cap (only MCP outer timeout)."""
    if not is_postgres_query_tool(server_name, tool_name):
        return None
    sec = _env_float("AION_PG_QUERY_TIMEOUT_SEC", 60.0)
    return sec if sec > 0 else None

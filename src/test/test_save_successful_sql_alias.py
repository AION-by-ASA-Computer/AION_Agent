"""MCP tool argument aliases for SQL save tools."""

from __future__ import annotations

from src.runtime.mcp_tool_args import prepare_mcp_tool_arguments


def test_save_successful_sql_query_alias() -> None:
    args, err = prepare_mcp_tool_arguments(
        "memory-save_successful_sql",
        {
            "request": "Che pc ha Mario?",
            "query": "SELECT 1",
            "namespace": "aion_am",
        },
    )
    assert err is None
    assert args["sql"] == "SELECT 1"
    assert args["project"] == "aion_am"


def test_sql_memory_save_alias() -> None:
    args, err = prepare_mcp_tool_arguments(
        "sql_memory_save",
        {"user_request": "test", "query": "SELECT 2", "drawer": "proj1"},
    )
    assert err is None
    assert args["sql"] == "SELECT 2"
    assert args["project"] == "proj1"
    assert args["request"] == "test"

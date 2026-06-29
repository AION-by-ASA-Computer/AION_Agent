"""Test pre-validazione argomenti tool MCP."""
from __future__ import annotations

import json

from src.runtime.mcp_tool_args import (
    normalize_workspace_relative_path,
    prepare_mcp_tool_arguments,
)


def test_normalize_workspace_relative_path_adds_prefix():
    assert normalize_workspace_relative_path("frisian_horse.html") == "workspace/frisian_horse.html"
    assert normalize_workspace_relative_path("workspace/a.py") == "workspace/a.py"
    assert (
        normalize_workspace_relative_path("workspace/workspace/promo/x.html")
        == "workspace/promo/x.html"
    )


def test_write_path_auto_normalized():
    args, err = prepare_mcp_tool_arguments(
        "sandbox_write_workspace_file",
        {"relative_path": "page.html", "content": "<html></html>"},
    )
    assert err is None
    assert args["relative_path"] == "workspace/page.html"


def test_edit_missing_relative_path_returns_json_error():
    args, err = prepare_mcp_tool_arguments(
        "sandbox_edit_workspace_file",
        {"old_string": "foo", "replace_all": False},
    )
    assert err is not None
    data = json.loads(err)
    assert data["ok"] is False
    assert data["error"] == "missing_arguments"
    assert "relative_path" in data["missing"]
    assert "new_string" in data["missing"]


def test_edit_alias_path_to_relative_path():
    args, err = prepare_mcp_tool_arguments(
        "sandbox_edit_workspace_file",
        {
            "path": "workspace/a.py",
            "old_string": "x",
            "new_string": "y",
        },
    )
    assert err is None
    assert args["relative_path"] == "workspace/a.py"
    assert "path" not in args


def test_edit_all_required_ok():
    args, err = prepare_mcp_tool_arguments(
        "sandbox_edit_workspace_file",
        {
            "relative_path": "workspace/a.py",
            "old_string": "x",
            "new_string": "y",
        },
    )
    assert err is None
    assert args["relative_path"] == "workspace/a.py"


def test_trace_context_preserved():
    args, err = prepare_mcp_tool_arguments(
        "sandbox_edit_workspace_file",
        {
            "relative_path": "workspace/a.py",
            "old_string": "x",
            "new_string": "y",
            "_trace_context": {"traceparent": "00-abc"},
        },
    )
    assert err is None
    assert args["_trace_context"] == {"traceparent": "00-abc"}

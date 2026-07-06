"""Tests for OpenCode-style tool settlement."""

import json

from src.runtime.mcp_tool_args import prepare_mcp_tool_arguments
from src.runtime.tool_settlement import (
    is_phantom_tool,
    phantom_tool_message,
    settle_tool_call,
)


def test_phantom_aion_artifact():
    assert is_phantom_tool("aion_artifact")
    err = settle_tool_call("aion_artifact", {"identifier": "x"})
    assert err is not None
    data = json.loads(err)
    assert data["error"] == "phantom_tool"
    assert "sandbox_write_workspace_file" in data["hint"]


def test_phantom_message_json():
    msg = phantom_tool_message("artifact")
    data = json.loads(msg)
    assert data["tool"] == "artifact"


def test_edit_empty_args_preflight():
    _, err = prepare_mcp_tool_arguments("sandbox_edit_workspace_file", {})
    assert err is not None
    data = json.loads(err)
    assert data["error"] == "missing_arguments"
    assert "old_string" in data["missing"]


def test_settle_empty_kwargs_when_recovery_disabled(monkeypatch):
    monkeypatch.setenv("AION_JSON_RECOVERY_ALLOW_EMPTY", "0")
    from importlib import reload
    import src.runtime.tool_settlement as ts

    reload(ts)
    err = ts.settle_tool_call("sandbox_edit_workspace_file", {})
    assert err is not None
    data = json.loads(err)
    assert data["error"] == "invalid_arguments"


def test_unknown_tool_with_registry():
    err = settle_tool_call(
        "totally_fake_tool",
        {},
        registered_tools={"sandbox_read_text_file", "skill_search"},
    )
    assert err is not None
    data = json.loads(err)
    assert data["error"] == "unknown_tool"


def test_valid_tool_not_settled():
    err = settle_tool_call(
        "sandbox_read_text_file",
        {"relative_path": "workspace/foo.js"},
        registered_tools={"sandbox_read_text_file"},
    )
    assert err is None

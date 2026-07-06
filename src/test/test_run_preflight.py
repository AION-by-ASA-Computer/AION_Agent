"""Preflight gates for sandbox run tools."""

import json
from pathlib import Path

from src.runtime.mcp_tool_args import preflight_run_file_tool


def test_run_node_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.session_workspace.session_root",
        lambda sid: tmp_path / sid,
    )
    sid = "sess-preflight"
    ws = tmp_path / sid / "workspace"
    ws.mkdir(parents=True)
    err = preflight_run_file_tool(
        "sandbox_run_node_file",
        {"relative_path": "workspace/missing.js"},
        sid,
    )
    assert err is not None
    data = json.loads(err)
    assert data["error"] == "file_not_found"


def test_run_node_empty_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.session_workspace.session_root",
        lambda sid: tmp_path / sid,
    )
    sid = "sess-empty"
    ws = tmp_path / sid / "workspace"
    ws.mkdir(parents=True)
    script = ws / "empty.js"
    script.write_text("", encoding="utf-8")
    err = preflight_run_file_tool(
        "sandbox_run_node_file",
        {"relative_path": "workspace/empty.js"},
        sid,
    )
    assert err is not None
    data = json.loads(err)
    assert data["error"] == "empty_file"

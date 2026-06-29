"""Exec allowlist JSON errors must surface stderr to the agent."""

from __future__ import annotations

import json

from src.runtime.mcp_tool_result import classify_tool_result_text


def test_exec_failure_surfaces_stderr_not_generic_tool_error() -> None:
    payload = {
        "ok": False,
        "exit_code": 1,
        "stderr": "Error: project pins profile 'aion-alibr' but it doesn't exist",
        "stdout": "",
        "command": ["wren", "--sql", "SELECT 1"],
    }
    is_err, normalized = classify_tool_result_text(
        json.dumps(payload), "sandbox_exec_allowlisted"
    )
    assert is_err
    data = json.loads(normalized)
    assert data["error"] == "exec_failed"
    assert "aion-alibr" in data["message"]

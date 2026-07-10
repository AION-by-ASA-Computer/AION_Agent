"""Tests for MCP tool result error classification."""

from __future__ import annotations

import json

from src.runtime.mcp_tool_result import (
    classify_tool_result_text,
    format_exception_for_tool,
)


def test_classify_empty_query_result_as_error():
    is_err, body = classify_tool_result_text("", "query")
    assert is_err is True
    data = json.loads(body)
    assert data.get("ok") is False


def test_classify_json_preflight_error():
    raw = json.dumps({"ok": False, "error": "missing sql"})
    is_err, body = classify_tool_result_text(raw, "query")
    assert is_err is True
    assert "missing sql" in body


def test_classify_postgres_syntax_in_text():
    raw = 'ERROR: syntax error at or near "FROM"'
    is_err, body = classify_tool_result_text(raw, "query")
    assert is_err is True
    assert "sql_execution_error" in body


def test_classify_success_json_array():
    raw = '[{"sscc": "123"}]'
    is_err, _ = classify_tool_result_text(raw, "query")
    assert is_err is False


def test_classify_ok_sandbox_run_with_ruff_noise():
    raw = (
        "OK\nExit code: 0\n--- stdout ---\nFibonacci\n"
        "[Avviso ruff (non bloccante)]\nruff failed\nRead-only file system (os error 30)"
    )
    is_err, body = classify_tool_result_text(raw, "sandbox_run_python_file")
    assert is_err is False
    assert body == raw


def test_format_exception_for_tool():
    body = format_exception_for_tool("query", ValueError("connection reset"))
    data = json.loads(body)
    assert data["ok"] is False
    assert "connection reset" in data["message"]


def test_classify_skill_view_not_error_despite_keywords():
    raw = "Plane Project Management. Error: this tool failed sometimes due to Pydantic Validation exception."
    is_err, body = classify_tool_result_text(raw, "skill_view")
    assert is_err is False
    assert body == raw

"""Tests for MCP tool result error classification."""

from __future__ import annotations

import json

from src.runtime.mcp_tool_result import (
    build_timeout_message,
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


def test_timeout_message_for_postgres_keeps_sql_guidance():
    msg = build_timeout_message("toolbox-postgres", "query")
    assert "PostgreSQL cap" in msg
    assert "Heavy JOINs" in msg


def test_timeout_message_for_document_tools_is_not_about_sql():
    """A PostgreSQL hint on an OCR timeout actively derails the model."""
    for tool in ("ocr_file", "doc_ingest"):
        msg = build_timeout_message("ocr", tool)
        assert "PostgreSQL" not in msg
        assert "JOIN" not in msg
        assert "doc_ingest" in msg
        assert "first_page" in msg


def test_timeout_message_generic_tool_has_no_sql_or_false_recycle_claim():
    msg = build_timeout_message("session_sandbox", "sandbox_run_python_file")
    assert "PostgreSQL" not in msg
    # Only the Postgres path actually restarts the worker.
    assert "recycled" not in msg
    assert "AION_MCP_TOOL_RESULT_TIMEOUT" in msg


def test_timeout_message_handles_prefixed_tool_names():
    msg = build_timeout_message("ocr", "ocr-doc_ingest")
    assert "doc_ingest" in msg
    assert "PostgreSQL" not in msg


def test_classify_skill_view_not_error_despite_keywords():
    raw = "Plane Project Management. Error: this tool failed sometimes due to Pydantic Validation exception."
    is_err, body = classify_tool_result_text(raw, "skill_view")
    assert is_err is False
    assert body == raw

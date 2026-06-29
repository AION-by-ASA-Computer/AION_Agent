"""sandbox_run_node_file path validation."""

import pytest

from src.tools.session_code import SessionSandboxExecutor


def test_run_file_rejects_js_with_python_hint():
    ex = SessionSandboxExecutor("test-session-node-hint")
    out = ex.run_file("workspace/create_doc.js")
    assert "sandbox_run_node_file" in out


def test_run_node_file_rejects_py():
    ex = SessionSandboxExecutor("test-session-node-hint")
    out = ex.run_node_file("workspace/script.py")
    assert "sandbox_run_python_file" in out

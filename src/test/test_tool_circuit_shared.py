"""Shared tool circuit breaker tests."""

from __future__ import annotations

import json

import pytest

from src.runtime.tool_circuit import (
    maybe_block_repeat_preflight,
    record_preflight_failure,
    reset_session_circuit,
)


@pytest.fixture(autouse=True)
def _enable_circuit(monkeypatch):
    monkeypatch.setenv("AION_TOOL_CIRCUIT_BREAKER_ENABLED", "1")
    monkeypatch.setenv("AION_TOOL_CIRCUIT_BREAKER_MAX", "2")
    from src.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_circuit_blocks_after_repeated_preflight_failures():
    sid = "sess-cb-1"
    tool = "sandbox_write_workspace_file"
    args = {"relative_path": "workspace/foo.py", "content": ""}
    err = json.dumps({"ok": False, "error": "missing_arguments"})
    reset_session_circuit(sid)
    assert maybe_block_repeat_preflight(sid, tool, args) is None
    record_preflight_failure(sid, tool, args, err)
    assert maybe_block_repeat_preflight(sid, tool, args) is None
    record_preflight_failure(sid, tool, args, err)
    blocked = maybe_block_repeat_preflight(sid, tool, args)
    assert blocked is not None
    data = json.loads(blocked)
    assert data.get("error") == "circuit_breaker"

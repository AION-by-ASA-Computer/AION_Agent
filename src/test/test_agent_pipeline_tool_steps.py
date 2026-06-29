"""Regression: tool step queue must not duplicate DB records."""

from src.runtime.tool_step_queue import queue_tool_step


def test_tool_end_without_call_id_single_append():
    pending: list = []
    ids: dict = {}
    queue_tool_step(
        pending,
        ids,
        {"name": "grep_search", "output": "found 3 matches"},
    )
    assert len(pending) == 1
    assert pending[0]["name"] == "grep_search"
    assert pending[0]["pending_update"] is False


def test_tool_end_with_known_call_id_pending_update():
    pending: list = []
    ids: dict = {}
    queue_tool_step(
        pending,
        ids,
        {"id": "tc-1", "name": "web_search", "input": {"q": "aion"}},
        is_start=True,
    )
    queue_tool_step(
        pending,
        ids,
        {"id": "tc-1", "name": "web_search", "output": "results"},
    )
    assert len(pending) == 2
    assert pending[0]["step_id"] == "tc-1"
    assert pending[1]["pending_update"] is True
    assert pending[1]["step_id"] == "tc-1"

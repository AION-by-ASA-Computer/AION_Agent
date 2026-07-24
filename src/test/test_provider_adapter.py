"""Provider adapter normalization tests."""

from types import SimpleNamespace

from src.runtime.provider_adapter import (
    normalize_stream_chunk,
    normalize_tool_call_id,
    repair_orphan_tool_results,
    skip_incomplete_assistant_turns,
)


def test_normalize_stream_chunk_length_emits_truncation():
    chunk = SimpleNamespace(
        content="",
        meta={"finish_reason": "length"},
        finish_reason="length",
        reasoning=None,
    )
    out = normalize_stream_chunk(chunk)
    types = [e["type"] for e in out["events"]]
    assert "stream_end" in types
    assert "turn_status" in types


def test_normalize_tool_call_id_sanitizes():
    assert normalize_tool_call_id("call/1!") == "call_1_"


def test_repair_orphan_tool_results_appends_stub():
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "abc"}]},
    ]
    fixed = repair_orphan_tool_results(msgs)
    assert fixed[-1]["role"] == "tool"
    assert fixed[-1]["tool_call_id"] == "abc"


def test_skip_incomplete_assistant_turns():
    msgs = [{"role": "assistant", "content": "   "}]
    assert skip_incomplete_assistant_turns(msgs) == []

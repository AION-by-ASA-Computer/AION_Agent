"""Tests for turn outcome classification."""

from __future__ import annotations

from src.runtime.turn_diagnostics import classify_turn_outcome


def test_empty_final_with_tools():
    out = classify_turn_outcome(
        session_id="sess",
        profile="postgres_metadata_assistant",
        stop_reason="completed",
        final_text="",
        full_reasoning="long " * 50,
        tool_calls_count=2,
        tool_events_count=4,
        new_messages=[
            type(
                "M",
                (),
                {
                    "role": type("R", (), {"value": "assistant"})(),
                    "tool_calls": [1],
                    "content": "",
                },
            )()
        ],
        context_stats={"total": 25000, "message_count": 674},
        max_agent_steps=10,
        llm_steps=10,
    )
    assert out["code"] == "tools_without_final_answer"
    assert out["user_visible_warning"]
    assert "674" in out["user_visible_warning"]


def test_user_cancelled_no_warning():
    """User-initiated cancel must never surface the MemPalace scary warning."""
    for stop in ("user_cancelled", "cancelled", "session_cancelled_by_user"):
        out = classify_turn_outcome(
            session_id="sess",
            profile="aion_std",
            stop_reason=stop,
            final_text="",
            full_reasoning="long " * 50,
            tool_calls_count=3,
            tool_events_count=6,
            new_messages=[],
            context_stats={"total": 30000, "message_count": 200},
        )
        assert out["code"] == "user_cancelled", f"Expected user_cancelled for stop={stop!r}, got {out['code']!r}"
        assert out["user_visible_warning"] is None, (
            f"No warning should be shown to user on cancel (stop={stop!r})"
        )


def test_plan_created_without_final_text():
    out = classify_turn_outcome(
        session_id="sess",
        profile="aion_std",
        stop_reason="completed",
        final_text="",
        full_reasoning="",
        tool_calls_count=2,
        tool_events_count=2,
        new_messages=[],
        plan_intercepts=1,
    )
    assert out["code"] == "plan_created"
    assert out.get("user_visible_warning") is None
    assert out.get("suggested_final_text")
    assert "Plan" in out["suggested_final_text"]


def test_reasoning_budget_with_tools_suggests_continue():
    out = classify_turn_outcome(
        session_id="sess",
        profile="generic_assistant",
        stop_reason="reasoning_budget",
        final_text="",
        full_reasoning="x" * 3000,
        tool_calls_count=14,
        tool_events_count=28,
        new_messages=[],
    )
    assert out["code"] == "tools_without_final_answer"
    assert out.get("suggested_final_text")
    assert "Continua" in out["suggested_final_text"]


def test_stream_loop_resets_reasoning_per_llm_call():
    from src.runtime.stream.loop import StreamLoop

    sl = object.__new__(StreamLoop)
    sl.reasoning_events = 200
    sl.reasoning_chars = 5000
    sl.reasoning_guard_logged = True
    sl.reasoning_no_tool_warned = True
    StreamLoop.reset_reasoning_window(sl)
    assert sl.reasoning_events == 0
    assert sl.reasoning_chars == 0
    assert sl.reasoning_guard_logged is False
    assert sl.reasoning_no_tool_warned is False


def test_log_turn_stop_accepts_snapshot_metrics(monkeypatch):
    from src.runtime.turn_diagnostics import log_turn_stop

    captured: list[dict] = []

    def _fake_append(_path, record):
        captured.append(record)

    monkeypatch.setattr("src.runtime.turn_diagnostics.append_jsonl", _fake_append)
    log_turn_stop(
        "sess-1",
        "tool_events_limit",
        location="test",
        tool_events=61,
        max_tool_events=60,
        llm_calls=20,
    )
    # WARNING log always fires; JSONL only when diagnostics enabled — no assert on captured

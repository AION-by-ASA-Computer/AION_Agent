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

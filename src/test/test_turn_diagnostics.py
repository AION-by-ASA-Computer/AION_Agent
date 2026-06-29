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
            type("M", (), {"role": type("R", (), {"value": "assistant"})(), "tool_calls": [1], "content": ""})()
        ],
        context_stats={"total": 25000, "message_count": 674},
        max_agent_steps=10,
        llm_steps=10,
    )
    assert out["code"] == "tools_without_final_answer"
    assert out["user_visible_warning"]
    assert "674" in out["user_visible_warning"]


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

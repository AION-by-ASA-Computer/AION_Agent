"""Tests for TimelineBuilder outcome / error segments."""

from __future__ import annotations

from src.runtime.timeline_builder import TimelineBuilder


def test_timeline_builder_turn_outcome_warning_segment():
    tb = TimelineBuilder()
    tb.apply_chunk(
        {
            "type": "turn_outcome",
            "code": "reasoning_budget_no_answer",
            "message": "Interrotto: reasoning oltre soglia.",
            "details": {"reasoning_effort": "min"},
        }
    )
    segs = tb.to_list()
    assert len(segs) == 1
    assert segs[0]["kind"] == "status"
    assert segs[0]["tone"] == "warning"
    assert segs[0]["outcomeCode"] == "reasoning_budget_no_answer"


def test_timeline_builder_error_as_warning_status():
    tb = TimelineBuilder()
    tb.apply_chunk({"type": "error", "content": "Hard-stop reasoning guard"})
    segs = tb.to_list()
    assert len(segs) == 1
    assert segs[0]["kind"] == "status"
    assert segs[0]["tone"] == "warning"

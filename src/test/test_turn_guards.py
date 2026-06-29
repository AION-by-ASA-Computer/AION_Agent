"""Tests for TurnGuards budget module."""
import time

from src.runtime.turn.turn_guards import TurnGuards


def test_turn_guards_tool_call_limit(monkeypatch):
    monkeypatch.setenv("AION_TOOL_CALLS_MAX_PER_TURN", "2")
    g = TurnGuards(message_source="user_input", loop_time_fn=time.time)
    assert g.on_tool_start() is None
    assert g.on_tool_start() is None
    decision = g.on_tool_start()
    assert decision is not None
    assert decision.should_stop
    assert decision.stop_reason == "tool_calls"


def test_turn_guards_no_progress(monkeypatch):
    monkeypatch.setenv("AION_NO_PROGRESS_TIMEOUT_SEC", "1")
    t = [1000.0]

    def _time():
        return t[0]

    g = TurnGuards(message_source="user_input", loop_time_fn=_time)
    g.state.last_progress_at = 1000.0
    t[0] = 1002.0
    decision = g.check_no_progress()
    assert decision.should_stop
    assert decision.stop_reason == "no_progress"


def test_turn_guards_reasoning_effort(monkeypatch):
    monkeypatch.setenv("AION_REASONING_MAX_CHARS", "20000")
    monkeypatch.setenv("AION_REASONING_MAX_EVENTS", "240")

    # 1. Medium (default fallback)
    g_med = TurnGuards(message_source="user_input", reasoning_effort="medium")
    assert g_med.max_reasoning_chars == 20000
    assert g_med.max_reasoning_events == 240

    # 2. Min (low thinking effort)
    g_min = TurnGuards(message_source="user_input", reasoning_effort="min")
    assert g_min.max_reasoning_chars == 2000
    assert g_min.max_reasoning_events == 30

    # 3. Max (high thinking effort)
    g_max = TurnGuards(message_source="user_input", reasoning_effort="max")
    assert g_max.max_reasoning_chars == 40000
    assert g_max.max_reasoning_events == 480


def test_dynamic_thinking_token_budget(monkeypatch):
    from src.runtime.reasoning_effort import merge_generation_kwargs

    # Min effort: enable_thinking is False, thinking_token_budget is popped
    base = {"extra_body": {"thinking_token_budget": 1000}}
    res_min = merge_generation_kwargs(base, "min")
    assert res_min["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert "thinking_token_budget" not in res_min["extra_body"]

    # Medium effort: enable_thinking is True, thinking_token_budget is 1024 by default
    res_med = merge_generation_kwargs({}, "medium")
    assert res_med["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    assert res_med["extra_body"]["thinking_token_budget"] == 1024

    # Max effort: enable_thinking is True, thinking_token_budget is 2048 by default
    res_max = merge_generation_kwargs({}, "max")
    assert res_max["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    assert res_max["extra_body"]["thinking_token_budget"] == 2048

    # Effort-specific override: AION_THINKING_TOKEN_BUDGET_MEDIUM takes precedence over default
    monkeypatch.setenv("AION_THINKING_TOKEN_BUDGET_MEDIUM", "500")
    res_med_override = merge_generation_kwargs({}, "medium")
    assert res_med_override["extra_body"]["thinking_token_budget"] == 500

    # Global override: AION_THINKING_TOKEN_BUDGET takes precedence over everything
    monkeypatch.setenv("AION_THINKING_TOKEN_BUDGET", "99")
    res_over = merge_generation_kwargs({}, "medium")
    assert res_over["extra_body"]["thinking_token_budget"] == 99



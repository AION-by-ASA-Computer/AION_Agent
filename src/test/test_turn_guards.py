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


def test_reasoning_hard_stop_requires_chars_for_event_only_guard():
    """Fragmented reasoning chunks should not hard-stop on events alone."""
    max_chars = 20000
    max_events = 480
    reasoning_chars = 5540
    reasoning_events = 481
    over_events = reasoning_events > max_events
    over_chars = reasoning_chars > max_chars
    min_chars_for_event_guard = max(6000, int(max_chars * 0.4))
    hard_stop = over_chars or (
        over_events and reasoning_chars >= min_chars_for_event_guard
    )
    assert not hard_stop

    reasoning_chars_high = 12000
    hard_stop_high = over_chars or (
        over_events and reasoning_chars_high >= min_chars_for_event_guard
    )
    assert hard_stop_high


def test_turn_budget_load_overrides(monkeypatch):
    monkeypatch.setenv("AION_TOOL_CALLS_MAX_PER_TURN", "24")
    from src.runtime.turn_budget import TurnBudget

    budget = TurnBudget.load(
        overrides={"max_tool_calls": 3, "no_progress_timeout": 11.5}
    )
    assert budget.max_tool_calls == 3
    assert budget.no_progress_timeout == 11.5


def test_dynamic_thinking_token_budget(monkeypatch):
    from src.runtime.reasoning_effort import merge_generation_kwargs

    monkeypatch.delenv("AION_THINKING_TOKEN_BUDGET", raising=False)
    monkeypatch.delenv("AION_THINKING_TOKEN_BUDGET_MEDIUM", raising=False)
    monkeypatch.delenv("AION_THINKING_TOKEN_BUDGET_MAX", raising=False)
    monkeypatch.delenv("AION_REASONING_EFFORT_MAX_BUDGET", raising=False)
    monkeypatch.delenv("AION_NATIVE_REASONING_DIALECT", raising=False)
    monkeypatch.delenv("AION_NATIVE_REASONING_EFFORT_VALUES", raising=False)

    # Off: enable_thinking is False, thinking_token_budget is popped
    base = {"extra_body": {"thinking_token_budget": 1000}}
    res_off = merge_generation_kwargs(base, "off")
    assert res_off["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert "thinking_token_budget" not in res_off["extra_body"]

    res_min = merge_generation_kwargs({}, "min")
    assert res_min["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    assert res_min["reasoning_effort"] == "low"

    # Medium/max: native reasoning_effort, no default token cap
    res_med = merge_generation_kwargs({}, "medium")
    assert res_med["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    assert "thinking_token_budget" not in res_med["extra_body"]
    assert res_med["reasoning_effort"] == "medium"

    res_max = merge_generation_kwargs({}, "max")
    assert res_max["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    assert "thinking_token_budget" not in res_max["extra_body"]
    assert res_max["reasoning_effort"] in ("xhigh", "high", "max")

    # Effort-specific override: AION_THINKING_TOKEN_BUDGET_MEDIUM is opt-in
    monkeypatch.setenv("AION_THINKING_TOKEN_BUDGET_MEDIUM", "500")
    res_med_override = merge_generation_kwargs({}, "medium")
    assert res_med_override["extra_body"]["thinking_token_budget"] == 500

    # Global override: AION_THINKING_TOKEN_BUDGET applies to medium/max, not min
    monkeypatch.setenv("AION_THINKING_TOKEN_BUDGET", "99")
    res_min_global = merge_generation_kwargs({}, "min")
    assert "thinking_token_budget" not in res_min_global["extra_body"]
    res_over = merge_generation_kwargs({}, "medium")
    assert res_over["extra_body"]["thinking_token_budget"] == 99

    monkeypatch.setenv("AION_THINKING_TOKEN_BUDGET_MIN", "256")
    res_min_dedicated = merge_generation_kwargs({}, "min")
    assert res_min_dedicated["extra_body"]["thinking_token_budget"] == 256

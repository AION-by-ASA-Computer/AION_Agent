from src.runtime.long_run_mode import (
    build_long_run_system_prompt,
    long_run_blocked_tool_names,
    long_run_turn_budget,
)


def test_long_run_prompt_mentions_sandbox():
    text = build_long_run_system_prompt()
    assert "LONG RUN MODE" in text
    assert "sandbox" in text.lower()


def test_long_run_budget_defaults():
    b = long_run_turn_budget()
    assert b.turn_timeout >= 600
    assert b.max_tool_calls >= 100


def test_blocked_tools_include_plan():
    blocked = long_run_blocked_tool_names()
    assert "draft_execution_plan" in blocked

"""Tests for consecutive tool-error recovery."""

from __future__ import annotations

from unittest.mock import MagicMock

from haystack.dataclasses import ChatMessage, ChatRole

from src.runtime.tool_error_recovery import (
    ToolErrorTracker,
    build_recovery_prompt,
    get_tracker,
    record_tool_error,
    record_tool_success,
    recover_from_consecutive_tool_errors,
    reset_tracker,
    tool_error_threshold,
)


def test_record_tool_error_triggers_after_threshold():
    reset_tracker("sess-ter")
    threshold = tool_error_threshold()
    for _ in range(threshold - 1):
        assert record_tool_error("sess-ter", "create_project", "HTTP 400") is None
    hit = record_tool_error("sess-ter", "create_project", "HTTP 409")
    assert hit is not None
    assert hit["consecutive_errors"] >= threshold


def test_record_tool_success_resets_counter():
    reset_tracker("sess-ter2")
    record_tool_error("sess-ter2", "create_project", "HTTP 400")
    record_tool_error("sess-ter2", "create_project", "HTTP 409")
    record_tool_success("sess-ter2")
    assert get_tracker("sess-ter2").consecutive_errors == 0


def test_build_recovery_prompt_lists_recent_errors():
    tracker = ToolErrorTracker(threshold=2)
    tracker.record_error("create_project", "HTTP 409: name taken")
    tracker.record_error("create_project", "HTTP 400: invalid identifier")
    prompt = build_recovery_prompt(tracker)
    assert "create_project" in prompt
    assert "HTTP 409" in prompt
    assert "Do NOT repeat" in prompt


def test_on_exit_hook_injects_system_and_continues():
    from src.runtime.turn_compaction import set_turn_runtime

    set_turn_runtime(
        session_id="sess-hook",
        loop=None,
        queue=None,
        stop_event=None,
        agent=None,
        profile_name="test",
        user_id="u1",
    )
    reset_tracker("sess-hook")
    record_tool_error("sess-hook", "create_project", "HTTP 400")
    record_tool_error("sess-hook", "create_project", "HTTP 409")

    state = MagicMock()
    state.get.return_value = [
        ChatMessage.from_assistant(
            "The previous tool calls returned consecutive tool errors."
        )
    ]

    recover_from_consecutive_tool_errors(state)

    state.set.assert_any_call("continue_run", True)
    messages_arg = None
    for call in state.set.call_args_list:
        if call.args and call.args[0] == "messages":
            messages_arg = call.args[1]
            break
    assert messages_arg is not None
    assert any(
        getattr(m, "role", None) == ChatRole.SYSTEM
        or str(getattr(m, "role", "")).endswith("system")
        for m in messages_arg
    )

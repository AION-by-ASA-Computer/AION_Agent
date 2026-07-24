"""Tests for autonomous context-window recovery."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from haystack.dataclasses import ChatMessage

from src.haystack_chat import chat_message_text
from src.runtime.context_recovery import (
    build_context_recovery_prompt,
    max_context_recovery_attempts,
    should_attempt_context_recovery,
)
from src.runtime.turn_compaction import (
    mechanical_shrink_conversation,
    tool_result_max_chars_for,
    truncate_tool_result,
)


class _FakeContextError(Exception):
    pass


def test_should_attempt_context_recovery_for_context_length():
    exc = _FakeContextError(
        "litellm.ContextWindowExceededError: context length exceeded"
    )
    assert should_attempt_context_recovery(exc, 0) is True
    assert should_attempt_context_recovery(exc, max_context_recovery_attempts()) is False


def test_build_context_recovery_prompt_includes_failure():
    prompt = build_context_recovery_prompt(_FakeContextError("too many tokens"))
    assert "context window exceeded" in prompt.lower()
    assert "too many tokens" in prompt


def test_mechanical_shrink_replaces_oldest_tool_outputs():
    origin = ChatMessage.from_assistant("call")
    convo = [
        ChatMessage.from_user("go"),
        ChatMessage.from_tool(tool_result="a" * 5000, origin=origin),
        ChatMessage.from_tool(tool_result="b" * 5000, origin=origin),
        ChatMessage.from_tool(tool_result="c" * 5000, origin=origin),
        ChatMessage.from_tool(tool_result="d" * 5000, origin=origin),
    ]
    shrunk, count = mechanical_shrink_conversation(convo, keep_recent_tools=2)
    assert count == 2
    assert "removed to free context" in chat_message_text(shrunk[1])
    assert chat_message_text(shrunk[-1]) == "d" * 5000


def test_web_fetch_has_lower_default_cap():
    with patch.dict(
        os.environ,
        {"AION_WEB_FETCH_MAX_CHARS": "6000", "AION_TOOL_RESULT_MAX_CHARS": "24000"},
        clear=False,
    ):
        cap = tool_result_max_chars_for("web_fetch_page")
        assert cap == 6000
        out = truncate_tool_result("x" * 20000, tool_name="web_fetch_page")
    assert len(out) < 20000


def test_emergency_compact_returns_smaller_message_list():
    from src.runtime.turn_compaction import emergency_compact_messages

    origin = ChatMessage.from_assistant("call")
    convo = [ChatMessage.from_user("task")]
    for i in range(12):
        convo.append(ChatMessage.from_tool(tool_result=f"page-{i} " + "z" * 8000, origin=origin))
    agent = MagicMock()
    with patch(
        "src.runtime.turn_compaction._estimate_prompt_total",
        side_effect=[
            {"total": 120000, "max_prompt": 131072, "messages": 100000, "overhead": 20000},
            {"total": 90000, "max_prompt": 131072, "messages": 70000, "overhead": 20000},
        ],
    ):
        out = emergency_compact_messages(agent, convo, force_sync=False, aggressive=False)
    assert out is not None
    assert len(out) < len(convo)

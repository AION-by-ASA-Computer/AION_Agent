"""Tests for intra-turn tool truncation and budget helpers."""

from __future__ import annotations

import os
from unittest.mock import patch

from haystack.dataclasses import ChatMessage

from src.haystack_chat import chat_message_text
from src.runtime.turn_compaction import (
    mechanical_shrink_conversation,
    truncate_tool_result,
)


def test_truncate_tool_result_caps_huge_output():
    with patch.dict(os.environ, {"AION_TOOL_RESULT_MAX_CHARS": "1000"}, clear=False):
        big = "x" * 5000
        out = truncate_tool_result(big, tool_name="mail_fetch")
        assert len(out) < 5000
        assert "troncato" in out.lower()


def test_mechanical_shrink_keeps_recent_tools():
    origin = ChatMessage.from_assistant("x")
    convo = [
        ChatMessage.from_tool(tool_result="old", origin=origin),
        ChatMessage.from_tool(tool_result="new", origin=origin),
    ]
    out, n = mechanical_shrink_conversation(convo, keep_recent_tools=1)
    assert n == 1
    assert "removed to free context" in chat_message_text(out[0])
    assert chat_message_text(out[1]) == "new"

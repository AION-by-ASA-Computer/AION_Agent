"""Compaction policy cut-point tests."""

from haystack.dataclasses import ChatMessage

from src.haystack_chat import chat_message_text
from src.runtime.compaction import find_valid_cut_index, is_valid_cut_index


def test_is_valid_cut_index_rejects_tool_role():
    origin = ChatMessage.from_assistant("calling tool")
    tool_msg = ChatMessage.from_tool(tool_result="result", origin=origin)
    role = str(getattr(tool_msg.role, "value", tool_msg.role))
    assert role == "tool"
    assert is_valid_cut_index([tool_msg], 0) is False


def test_find_valid_cut_index_respects_keep_last():
    msgs = [
        ChatMessage.from_user("u"),
        ChatMessage.from_assistant("a"),
        ChatMessage.from_user("u2"),
    ]
    cut = find_valid_cut_index(msgs, keep_last=1)
    assert cut == 2


def test_find_valid_cut_index_returns_negative_when_too_short():
    msgs = [ChatMessage.from_user("only")]
    assert find_valid_cut_index(msgs, keep_last=1) == -1

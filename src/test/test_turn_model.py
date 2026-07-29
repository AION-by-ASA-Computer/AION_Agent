"""Explicit turn model slicing."""

from haystack.dataclasses import ChatMessage

from src.runtime.turn.model import Turn, turn_new_messages_from_haystack


def test_turn_new_messages_uses_input_count():
    turn = Turn.start("sess", input_message_count=2)
    all_msgs = [
        ChatMessage.from_user("u1"),
        ChatMessage.from_assistant("a1"),
        ChatMessage.from_assistant("a2"),
    ]
    new = turn_new_messages_from_haystack(turn, all_msgs)
    assert len(new) == 1
    assert new[0].text == "a2"

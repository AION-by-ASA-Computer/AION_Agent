"""Harness v2 message layer tests."""

from haystack.dataclasses import ChatMessage

from src.haystack_chat import chat_message_text
from src.runtime.messages import (
    AionMessage,
    convert_to_llm,
    haystack_list_to_aion,
    injection_from_layer,
    layers_to_injections,
    transform_context,
)


def test_injection_wrapped_as_user_message():
    msgs = [
        AionMessage(role="user", content="hello"),
        injection_from_layer("ltm", "wake context"),
    ]
    out = convert_to_llm(transform_context(msgs))
    assert len(out) == 2
    assert "<ltm_context>" in chat_message_text(out[1])
    assert "wake context" in chat_message_text(out[1])


def test_compaction_summary_uses_xml_block():
    msgs = [AionMessage(role="compaction_summary", content="older turns")]
    out = convert_to_llm(msgs)
    assert len(out) == 1
    assert "<summary" in chat_message_text(out[0])
    assert "older turns" in chat_message_text(out[0])


def test_haystack_roundtrip_preserves_roles():
    hs = [
        ChatMessage.from_user("u1"),
        ChatMessage.from_assistant("a1"),
    ]
    aion = haystack_list_to_aion(hs)
    assert [m.role for m in aion] == ["user", "assistant"]


def test_layers_to_injections_maps_keys():
    layers = [{"key": "skill_nudge", "text": "try skill x"}]
    inj = layers_to_injections(layers)
    assert len(inj) == 1
    assert inj[0].role == "injection"
    assert inj[0].meta.get("layer") == "skill_nudge"

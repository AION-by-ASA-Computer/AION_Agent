"""Adapters between Haystack ChatMessage, DB rows, and AionMessage."""

from __future__ import annotations

from typing import List

from haystack.dataclasses import ChatMessage

from src.haystack_chat import chat_message_text
from src.runtime.messages.convert import injection_from_layer
from src.runtime.messages.types import AionMessage


def haystack_to_aion(msg: ChatMessage) -> AionMessage:
    role = getattr(msg, "role", None)
    role_s = str(getattr(role, "value", role) or "user")
    text = chat_message_text(msg)
    if role_s == "assistant":
        return AionMessage(role="assistant", content=text)
    if role_s == "tool":
        return AionMessage(
            role="tool_result",
            content=text,
            meta={
                "tool_call_id": getattr(msg, "tool_call_id", None),
                "tool_name": getattr(msg, "name", None),
            },
        )
    return AionMessage(role="user", content=text)


def haystack_list_to_aion(messages: List[ChatMessage]) -> List[AionMessage]:
    return [haystack_to_aion(m) for m in messages]


def aion_to_haystack(messages: List[AionMessage]) -> List[ChatMessage]:
    from src.runtime.messages.convert import convert_to_llm

    return convert_to_llm(messages)


def layers_to_injections(
    layers: List[dict[str, str]],
) -> List[AionMessage]:
    """Build injection messages from turn_context prompt_inject_layers."""
    out: List[AionMessage] = []
    for layer in layers:
        key = str(layer.get("key") or "other")
        text = str(layer.get("text") or "").strip()
        if text:
            out.append(injection_from_layer(key, text))
    return out

"""Convert AionMessage transcript to Haystack ChatMessage list for the agent."""

from __future__ import annotations

from typing import List

from haystack.dataclasses import ChatMessage

from src.runtime.messages.types import (
    AionMessage,
    wrap_compaction_summary,
    wrap_injection_text,
)


def convert_to_llm(messages: List[AionMessage]) -> List[ChatMessage]:
    out: List[ChatMessage] = []
    for msg in messages:
        if msg.role == "internal":
            continue
        if msg.role == "user":
            out.append(ChatMessage.from_user(msg.content))
        elif msg.role == "assistant":
            out.append(ChatMessage.from_assistant(msg.content))
        elif msg.role == "tool_result":
            name = msg.tool_name or "tool"
            out.append(
                ChatMessage.from_user(
                    f'<tool_result name="{name}">\n{msg.content}\n</tool_result>'
                )
            )
        elif msg.role == "injection":
            layer = msg.injection_layer or "other"
            wrapped = wrap_injection_text(layer, msg.content)
            if wrapped:
                out.append(ChatMessage.from_user(wrapped))
        elif msg.role == "compaction_summary":
            out.append(ChatMessage.from_user(wrap_compaction_summary(msg.content)))
    return out


def injection_from_layer(key: str, text: str) -> AionMessage:
    layer = key if key in {
        "ltm",
        "memory",
        "skill_nudge",
        "plan",
        "workspace",
        "attachments",
        "hooks",
    } else "other"
    return AionMessage(role="injection", content=text, meta={"layer": layer})

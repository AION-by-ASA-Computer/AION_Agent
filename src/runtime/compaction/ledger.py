"""Extract file/tool ledger from messages being summarized."""

from __future__ import annotations

from typing import List, Sequence

from haystack.dataclasses import ChatMessage

from src.haystack_chat import chat_message_text


def extract_tool_ledger(messages: Sequence[ChatMessage]) -> str:
    lines: List[str] = []
    for msg in messages:
        tool_name = getattr(msg, "name", None) or getattr(msg, "tool_name", None)
        role = str(getattr(msg.role, "value", msg.role))
        if tool_name:
            lines.append(f"- tool {tool_name} ({role})")
        text = chat_message_text(msg)
        if "sandbox_write" in text or "write_workspace" in text:
            lines.append(f"- file op mentioned in {role} message")
    if not lines:
        return ""
    return "Tools/files touched in summarized region:\n" + "\n".join(lines[:40])

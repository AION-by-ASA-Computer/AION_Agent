"""Valid compaction cut points (Pi-inspired: never split tool pairs)."""

from __future__ import annotations

from typing import Sequence

from haystack.dataclasses import ChatMessage


def is_valid_cut_index(messages: Sequence[ChatMessage], index: int) -> bool:
    if index < 0 or index >= len(messages):
        return False
    role = getattr(messages[index].role, "value", messages[index].role)
    role_s = str(role)
    if role_s == "tool":
        return False
    return role_s in ("user", "assistant", "system")


def find_valid_cut_index(
    messages: Sequence[ChatMessage],
    *,
    keep_last: int,
) -> int:
    """Return index to split head/tail; -1 if no valid cut."""
    if len(messages) <= keep_last + 1:
        return -1
    cut = len(messages) - keep_last
    while cut > 0 and not is_valid_cut_index(messages, cut):
        cut -= 1
    return cut if cut > 0 else -1

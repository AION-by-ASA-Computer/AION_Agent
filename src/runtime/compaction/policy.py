"""Unified compaction policy facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from haystack.dataclasses import ChatMessage

from src.memory.context_compressor import format_compaction_block, get_default_compressor
from src.runtime.compaction.cut_point import find_valid_cut_index
from src.runtime.compaction.ledger import extract_tool_ledger
from src.runtime.harness_flags import harness_v2_compaction
from src.haystack_chat import chat_message_text


@dataclass
class CompactionResult:
    messages: List[ChatMessage]
    did_compact: bool
    summary_text: str = ""


class CompactionPolicy:
    def should_use_v2(self) -> bool:
        return harness_v2_compaction()

    def compact_memory_fallback(
        self,
        messages: List[ChatMessage],
        *,
        keep_last: Optional[int] = None,
    ) -> CompactionResult:
        compressor = get_default_compressor()
        keep = keep_last if keep_last is not None else compressor.keep_last
        cut = find_valid_cut_index(messages, keep_last=keep)
        if cut < 0:
            return CompactionResult(messages=list(messages), did_compact=False)
        head, tail = messages[:cut], messages[cut:]
        transcript = "\n".join(
            f"{m.role}: {chat_message_text(m)[:2500]}" for m in head
        )
        ledger = extract_tool_ledger(head)
        summary_body = transcript[:12000]
        if ledger:
            summary_body = f"{summary_body}\n\n{ledger}"
        summary_msg = ChatMessage.from_user(
            format_compaction_block(summary_body, source_messages=len(head))
        )
        return CompactionResult(
            messages=[summary_msg] + list(tail),
            did_compact=True,
            summary_text=summary_body,
        )

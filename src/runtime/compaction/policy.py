"""Unified compaction policy facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from haystack.dataclasses import ChatMessage

from src.memory.context_compressor import (
    format_compaction_block,
    get_default_compressor,
)
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
        transcript = "\n".join(f"{m.role}: {chat_message_text(m)[:2500]}" for m in head)
        ledger = extract_tool_ledger(head)
        from src.runtime.tool_ledger import (
            ledger_summary_lines,
            offload_paths_for_session,
            render_ledger_table,
            tool_ledger_enabled,
        )

        if tool_ledger_enabled():
            session_id = ""
            try:
                from src.runtime.context import get_current_session_id

                session_id = (get_current_session_id() or "").strip()
            except Exception:
                pass
            if session_id:
                ledger = render_ledger_table(session_id) or ledger
                offload_block = "\n".join(offload_paths_for_session(session_id)[:40])
                if offload_block:
                    ledger = (
                        f"{ledger}\n\n<offloaded-results>\n"
                        f"{offload_block}\n</offloaded-results>"
                    )
                trace_lines = ledger_summary_lines(session_id)
                if trace_lines:
                    ledger = (
                        f"{ledger}\n\n<tool-trace>\n"
                        + "\n".join(trace_lines)
                        + "\n</tool-trace>"
                    )
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

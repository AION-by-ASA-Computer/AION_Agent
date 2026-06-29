"""Unit tests for STM context compression budgets."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

from haystack.dataclasses import ChatMessage

from src.haystack_chat import chat_message_text
from src.memory.context_compressor import (
    ContextCompressor,
    truncate_messages_to_prompt_budget,
)


def _msg(text: str, role: str = "user") -> ChatMessage:
    if role == "assistant":
        return ChatMessage.from_assistant(text)
    return ChatMessage.from_user(text)


def test_compress_trigger_is_model_window_times_threshold():
    comp = ContextCompressor(window_size=131_072, threshold=0.5, keep_last=4)
    assert comp.compress_trigger_tokens() == 65_536


def test_should_compress_at_trigger_including_overhead():
    comp = ContextCompressor(
        window_size=131_072, threshold=0.5, keep_last=4, reserve_output=16_384
    )
    overhead = 20_000
    trigger = comp.compress_trigger_tokens()
    below = [_msg("x" * 200) for _ in range(3)]
    assert comp.total_with_overhead(below, overhead) < trigger
    assert not comp.should_compress(below, fixed_overhead=overhead)
    big = [_msg("word " * 8000) for _ in range(6)]
    assert comp.total_with_overhead(big, overhead) >= trigger
    assert comp.should_compress(big, fixed_overhead=overhead)


def test_should_compress_when_over_api_prompt_budget_even_below_trigger():
    # Soglia alta così il budget API (window − reserve) scatta prima del trigger percentuale.
    comp = ContextCompressor(
        window_size=131_072, threshold=0.95, keep_last=4, reserve_output=16_384
    )
    overhead = 114_600
    messages = [_msg("x " * 40) for _ in range(8)]
    total = comp.total_with_overhead(messages, overhead)
    assert total >= comp.max_prompt_tokens()
    assert total < comp.compress_trigger_tokens()
    assert comp.should_compress(messages, fixed_overhead=overhead)


def test_compress_until_fits_reduces_message_count():
    comp = ContextCompressor(
        window_size=20_000, threshold=0.1, keep_last=2, reserve_output=1000
    )

    async def _noop(_head):
        return None

    async def _run():
        messages = [_msg(f"turn {i} " + ("data " * 200)) for i in range(10)]
        with patch(
            "src.memory.context_compressor.complete_text_sync",
            return_value="Sintesi compatta dei turni precedenti.",
        ):
            return await comp.compress_until_fits(
                messages,
                fixed_overhead=2000,
                pre_compression_hook=_noop,
                force=True,
            )

    out = asyncio.run(_run())
    assert len(out) <= 3
    head = chat_message_text(out[0])
    assert "[AION COMPACTION" in head or "CONTEXT SUMMARY" in head or "Sintesi" in head


def test_should_compress_few_huge_messages_over_budget():
    comp = ContextCompressor(
        window_size=131_072, threshold=0.5, keep_last=6, reserve_output=16_384
    )
    overhead = 20_000
    messages = [_msg("word " * 12000) for _ in range(6)]
    assert comp.should_compress(messages, fixed_overhead=overhead)


def test_truncate_messages_fits_prompt_budget():
    comp = ContextCompressor(
        window_size=10_000, threshold=0.5, keep_last=2, reserve_output=1000
    )
    max_prompt = comp.max_prompt_tokens()
    overhead = 3000
    messages = [_msg("x" * 5000) for _ in range(4)]
    out = truncate_messages_to_prompt_budget(
        messages,
        max_prompt_tokens=max_prompt,
        fixed_overhead=overhead,
        keep_last=2,
    )
    assert len(out) <= 4
    assert comp.total_with_overhead(out, overhead) <= max_prompt


def test_model_context_window_prefers_max_context_env():
    with patch.dict(
        os.environ,
        {
            "AION_MODEL_MAX_CONTEXT": "131072",
            "AION_CONTEXT_COMPRESS_MODEL_WINDOW": "32768",
        },
        clear=False,
    ):
        from src.memory.context_compressor import model_context_window

        assert model_context_window() == 131072

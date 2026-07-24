"""LLM provider normalization (Pi transformMessages / streamSimple inspired)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.runtime.harness_flags import harness_v2_provider
from src.runtime.reasoning_effort import generation_kwargs_for_agent


def provider_adapter_enabled() -> bool:
    return harness_v2_provider()


def normalize_stream_chunk(chunk: Any) -> Dict[str, Any]:
    meta = getattr(chunk, "meta", None) or {}
    fr = getattr(chunk, "finish_reason", None) or meta.get("finish_reason")
    reasoning = None
    chunk_reasoning = getattr(chunk, "reasoning", None)
    if chunk_reasoning is not None:
        if isinstance(chunk_reasoning, str):
            reasoning = chunk_reasoning
        elif hasattr(chunk_reasoning, "reasoning_text"):
            reasoning = chunk_reasoning.reasoning_text
    if not reasoning:
        reasoning = meta.get("reasoning") or meta.get("reasoning_content")
    events: List[Dict[str, Any]] = []
    if fr:
        events.append({"type": "stream_end", "finish_reason": fr})
        if fr == "length":
            events.append(
                {
                    "type": "turn_status",
                    "phase": "output_truncated",
                    "message": (
                        "LLM output was truncated (max_tokens). "
                        "Use smaller tool payloads and continue next step."
                    ),
                }
            )
    if reasoning:
        events.append({"type": "reasoning", "reasoning": reasoning})
    content = getattr(chunk, "content", None)
    if content is not None and content != "":
        events.append({"type": "token", "content": content})
    return {"events": events, "finish_reason": fr}


def merge_generation_kwargs(
    *,
    agent: Any,
    base: Optional[Dict[str, Any]] = None,
    reasoning_effort: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge agent/turn generation kwargs through the provider adapter."""
    merged = dict(base or {})
    gen = generation_kwargs_for_agent(agent, reasoning_effort) or {}
    merged.update(gen)
    if overrides:
        merged.update(overrides)
    return merged


_TOOL_ID_SAFE = re.compile(r"[^a-zA-Z0-9_-]")


def normalize_tool_call_id(tool_id: str, *, max_len: int = 64) -> str:
    raw = str(tool_id or "call")
    safe = _TOOL_ID_SAFE.sub("_", raw)[:max_len]
    return safe or "call"


def repair_orphan_tool_results(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Best-effort repair for OpenAI-style message dicts before LLM calls."""
    if not messages:
        return messages
    pending: set[str] = set()
    for msg in messages:
        role = msg.get("role")
        if role == "assistant":
            for tc in msg.get("tool_calls") or []:
                tid = (tc.get("id") if isinstance(tc, dict) else None) or ""
                if tid:
                    pending.add(str(tid))
        if role == "tool":
            tid = str(msg.get("tool_call_id") or "")
            pending.discard(tid)
    if not pending:
        return messages
    out = list(messages)
    for tid in pending:
        out.append(
            {
                "role": "tool",
                "tool_call_id": tid,
                "content": "[AION] Missing tool result repaired by provider adapter.",
            }
        )
    return out


def skip_incomplete_assistant_turns(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not messages:
        return messages
    last = messages[-1]
    if last.get("role") == "assistant" and not (last.get("content") or "").strip():
        return messages[:-1]
    return messages

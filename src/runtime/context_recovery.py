"""
Autonomous recovery when the agent hits context-window limits mid-turn.

Mirrors tool_error_recovery: compact context, inject a system recovery prompt,
and let the pipeline retry ``run_async`` without a new user message.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from haystack.dataclasses import ChatMessage

from src.haystack_chat import chat_message_text
from src.runtime.litellm_errors import (
    LiteLLMErrorCode,
    classify_litellm_error,
    is_context_length_error,
)

logger = logging.getLogger("aion.context_recovery")

_DEFAULT_MAX_ATTEMPTS = 2

_RECOVERY_PROMPT = """\
SYSTEM RECOVERY — context window exceeded. Do NOT stop or apologize.

The conversation history was automatically compacted so you can continue the same task.
Recovery rules:
1. Continue the user's original request from where you left off.
2. Do NOT repeat bulk web_fetch_page calls you already made — use notes you have or \
targeted smaller fetches.
3. Prefer writing deliverables (files, spreadsheets) over gathering more reference text.
4. If data is incomplete, produce the best partial artifact and note gaps briefly.
5. Only ask the user when a decision is truly blocking.

Recent failure: {error_summary}
"""


def max_context_recovery_attempts() -> int:
    raw = (os.getenv("AION_CONTEXT_RECOVERY_MAX") or "").strip()
    if not raw:
        return _DEFAULT_MAX_ATTEMPTS
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_MAX_ATTEMPTS


def context_recovery_enabled() -> bool:
    return os.getenv("AION_CONTEXT_RECOVERY", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def should_attempt_context_recovery(exc: BaseException, attempt: int) -> bool:
    if not context_recovery_enabled():
        return False
    if attempt >= max_context_recovery_attempts():
        return False
    code = classify_litellm_error(exc)
    return code == LiteLLMErrorCode.CONTEXT_LENGTH or is_context_length_error(exc)


def build_context_recovery_prompt(exc: BaseException) -> str:
    summary = str(exc).replace("\n", " ").strip()
    if len(summary) > 320:
        summary = summary[:317] + "..."
    if not summary:
        summary = "context window exceeded"
    return _RECOVERY_PROMPT.format(error_summary=summary)


def _turn_runtime_dict() -> Optional[Dict[str, Any]]:
    try:
        from src.runtime.turn_compaction import _turn_runtime
    except ImportError:
        return None
    if _turn_runtime is None:
        return None
    rt = _turn_runtime.get()
    return rt if isinstance(rt, dict) else None


def get_live_agent_messages(fallback: List[ChatMessage]) -> List[ChatMessage]:
    """Prefer Haystack execution state (includes tool results from this turn)."""
    try:
        from src.runtime.turn_compaction import _agent_exec_ctx
    except ImportError:
        return list(fallback)
    if _agent_exec_ctx is None:
        return list(fallback)
    exec_ctx = _agent_exec_ctx.get()
    if exec_ctx is None:
        return list(fallback)
    state = getattr(exec_ctx, "state", None)
    if state is None:
        return list(fallback)
    messages = None
    data = getattr(state, "_data", None) or getattr(state, "data", None)
    if isinstance(data, dict):
        messages = data.get("messages")
    if messages is None and hasattr(state, "get"):
        messages = state.get("messages")
    if isinstance(messages, list) and messages:
        return list(messages)
    return list(fallback)


def _emit_recovery_event(
    queue: Any,
    loop: Any,
    *,
    attempt: int,
    tokens_before: int,
    tokens_after: int,
) -> None:
    payload = {
        "type": "context_recovery",
        "attempt": attempt,
        "message": (
            "Context window exceeded — compacting history and retrying automatically "
            f"(attempt {attempt})."
        ),
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
    }
    try:
        if loop is not None:
            loop.call_soon_threadsafe(queue.put_nowait, payload)
        else:
            queue.put_nowait(payload)
    except Exception as exc:
        logger.debug("context_recovery SSE emit failed: %s", exc)


def attempt_context_recovery(
    *,
    agent: Any,
    messages: List[ChatMessage],
    exc: BaseException,
    attempt: int,
    queue: Any,
    loop: Any = None,
) -> Optional[List[ChatMessage]]:
    """
    Compact agent context and return messages for another ``run_async`` attempt.
    Returns None when compaction could not free enough space.
    """
    from src.runtime.turn_compaction import (
        _estimate_prompt_total,
        emergency_compact_messages,
    )

    live = get_live_agent_messages(messages)
    before_stats = _estimate_prompt_total(agent, live)
    compacted = emergency_compact_messages(
        agent,
        live,
        force_sync=True,
        aggressive=(attempt > 1),
    )
    if not compacted:
        logger.warning(
            "context_recovery: emergency compact failed attempt=%s session tokens=%s",
            attempt,
            before_stats.get("total"),
        )
        return None

    after_stats = _estimate_prompt_total(agent, compacted)
    recovery_msgs = list(compacted)
    recovery_msgs.append(ChatMessage.from_system(build_context_recovery_prompt(exc)))

    rt = _turn_runtime_dict()
    if rt is not None:
        rt["context_recovery_attempts"] = int(rt.get("context_recovery_attempts") or 0) + 1
        rt["extra_tokens"] = 0
        rt["last_compact_at"] = 0.0

    _emit_recovery_event(
        queue,
        loop,
        attempt=attempt,
        tokens_before=int(before_stats.get("total") or 0),
        tokens_after=int(after_stats.get("total") or 0),
    )
    logger.warning(
        "context_recovery attempt=%s tokens %s→%s messages=%d",
        attempt,
        before_stats.get("total"),
        after_stats.get("total"),
        len(recovery_msgs),
    )
    return recovery_msgs

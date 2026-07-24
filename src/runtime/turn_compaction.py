"""Compattazione contesto durante un turno agent (dopo tool / ragionamento)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from haystack.dataclasses import ChatMessage

from src.haystack_chat import chat_message_text
from src.memory.context_compressor import (
    count_tokens,
    estimate_agent_overhead_tokens,
    format_compaction_block,
    get_default_compressor,
)

logger = logging.getLogger("aion.turn_compaction")

_agent_exec_ctx: Any = None
_turn_runtime: Any = None

try:
    import contextvars

    _agent_exec_ctx = contextvars.ContextVar("aion_agent_exec_ctx", default=None)
    _turn_runtime = contextvars.ContextVar("aion_turn_runtime", default=None)
except ImportError:
    pass


def _env_bool(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def mid_turn_compaction_enabled() -> bool:
    return _env_bool("AION_CONTEXT_COMPRESS_MID_TURN", "1")


def mid_turn_reasoning_compaction_enabled() -> bool:
    from src.runtime.harness_flags import mid_turn_reasoning_compaction_enabled as _flag

    return _flag()


def mid_turn_sync_compaction_enabled() -> bool:
    from src.runtime.harness_flags import mid_turn_sync_compaction_enabled as _flag

    return _flag()


def tool_result_max_chars() -> int:
    try:
        return max(2000, int(os.getenv("AION_TOOL_RESULT_MAX_CHARS", "24000")))
    except ValueError:
        return 24000


_PER_TOOL_CAP_ENV: Dict[str, str] = {
    "web_fetch_page": "AION_WEB_FETCH_MAX_CHARS",
    "web_search": "AION_WEB_SEARCH_MAX_CHARS",
}

_PER_TOOL_DEFAULTS: Dict[str, int] = {
    "web_fetch_page": 6000,
    "web_search": 4000,
}


def tool_result_max_chars_for(tool_name: str) -> int:
    key = (tool_name or "").strip().lower()
    env_name = _PER_TOOL_CAP_ENV.get(key)
    if env_name:
        try:
            return max(500, int(os.getenv(env_name, str(_PER_TOOL_DEFAULTS.get(key, 6000)))))
        except ValueError:
            return _PER_TOOL_DEFAULTS.get(key, 6000)
    return tool_result_max_chars()


def truncate_tool_result(result: str, *, tool_name: str = "") -> str:
    """Riduce output tool enormi (es. 200 email) prima che entrino nel contesto Haystack."""
    text = str(result or "")
    cap = tool_result_max_chars_for(tool_name)
    if len(text) <= cap:
        return text
    head = text[: cap // 2]
    tail = text[-(cap // 4) :]
    omitted = len(text) - len(head) - len(tail)
    note = (
        f"\n\n[AION: output {tool_name or 'tool'} troncato — "
        f"{omitted} characters omitted. Request smaller batches or use filters.]\n"
    )
    return head + note + tail


def set_turn_runtime(
    *,
    session_id: str,
    loop: Any,
    queue: Any,
    stop_event: Any,
    agent: Any,
    profile_name: str,
    user_id: str,
) -> None:
    if _turn_runtime is None:
        return
    _turn_runtime.set(
        {
            "session_id": session_id,
            "loop": loop,
            "queue": queue,
            "stop_event": stop_event,
            "agent": agent,
            "profile_name": profile_name,
            "user_id": user_id,
            "extra_tokens": 0,
            "last_compact_at": 0.0,
            "llm_steps": 0,
            "tool_error_recovery_attempts": 0,
            "context_recovery_attempts": 0,
        }
    )
    try:
        from src.runtime.tool_error_recovery import reset_tracker

        reset_tracker(session_id)
    except Exception:
        pass


def bump_llm_step() -> int:
    if _turn_runtime is None:
        return 0
    rt = _turn_runtime.get()
    if not isinstance(rt, dict):
        return 0
    n = int(rt.get("llm_steps") or 0) + 1
    rt["llm_steps"] = n
    return n


def get_llm_step_count() -> int:
    if _turn_runtime is None:
        return 0
    rt = _turn_runtime.get()
    if not isinstance(rt, dict):
        return 0
    return int(rt.get("llm_steps") or 0)


def _mid_turn_debug_log(message: str, data: Dict[str, Any]) -> None:
    from src.runtime.turn_diagnostics import agent_debug_log

    agent_debug_log("H4", "turn_compaction:compact", message, data)


def set_agent_execution_context(exec_ctx: Any) -> None:
    if _agent_exec_ctx is not None:
        _agent_exec_ctx.set(exec_ctx)


def clear_agent_execution_context() -> None:
    if _agent_exec_ctx is not None:
        _agent_exec_ctx.set(None)


def clear_turn_runtime() -> None:
    if _turn_runtime is not None:
        _turn_runtime.set(None)
    clear_agent_execution_context()


def add_turn_token_estimate(delta: int) -> None:
    if _turn_runtime is None:
        return
    rt = _turn_runtime.get()
    if not isinstance(rt, dict):
        return
    rt["extra_tokens"] = int(rt.get("extra_tokens") or 0) + max(0, delta)


def _message_role_str(message: ChatMessage) -> str:
    role = getattr(message, "role", None)
    return str(role.value if hasattr(role, "value") else role or "user").lower()


def _split_system_and_conversation(
    messages: List[ChatMessage],
) -> tuple[List[ChatMessage], List[ChatMessage]]:
    system: List[ChatMessage] = []
    convo: List[ChatMessage] = []
    for m in messages:
        if _message_role_str(m) == "system":
            system.append(m)
        else:
            convo.append(m)
    return system, convo


def _estimate_prompt_total(
    agent: Any, messages: List[ChatMessage], extra: int = 0
) -> Dict[str, int]:
    overhead = estimate_agent_overhead_tokens(agent)
    msg_tokens = sum(count_tokens(chat_message_text(m)) for m in messages) + extra
    comp = get_default_compressor()
    total = msg_tokens + overhead
    return {
        "messages": msg_tokens,
        "overhead": overhead,
        "total": total,
        "trigger": comp.compress_trigger_tokens(),
        "max_prompt": comp.max_prompt_tokens(),
    }


_MECHANICAL_TOOL_PLACEHOLDER = (
    "[Earlier tool output removed to free context. "
    "Use targeted search or a smaller fetch if you need those details again.]"
)


def _tool_message_origin(msg: ChatMessage) -> Any:
    content = getattr(msg, "_content", None) or getattr(msg, "content", None)
    if isinstance(content, list):
        for part in content:
            origin = getattr(part, "origin", None)
            if origin is not None:
                return origin
    return getattr(msg, "_origin", None) or getattr(msg, "origin", None)


def _shrink_tool_message(msg: ChatMessage, new_text: str) -> ChatMessage:
    origin = _tool_message_origin(msg)
    if origin is None:
        origin = ChatMessage.from_assistant("tool")
    return ChatMessage.from_tool(tool_result=new_text, origin=origin)


def mechanical_shrink_conversation(
    convo: List[ChatMessage],
    *,
    keep_recent_tools: int = 3,
    placeholder: str = _MECHANICAL_TOOL_PLACEHOLDER,
) -> tuple[List[ChatMessage], int]:
    """
    Replace oldest tool-result bodies with a short placeholder.
    Returns (new_convo, count_shrunk).
    """
    tool_indices = [
        i
        for i, m in enumerate(convo)
        if _message_role_str(m) == "tool"
    ]
    if len(tool_indices) <= keep_recent_tools:
        return list(convo), 0

    shrink_indices = set(tool_indices[: len(tool_indices) - keep_recent_tools])
    if not shrink_indices:
        return list(convo), 0

    out: List[ChatMessage] = []
    shrunk = 0
    for i, m in enumerate(convo):
        if i not in shrink_indices:
            out.append(m)
            continue
        current = chat_message_text(m)
        if current.strip() == placeholder:
            out.append(m)
            continue
        out.append(_shrink_tool_message(m, placeholder))
        shrunk += 1
    return out, shrunk


def emergency_compact_messages(
    agent: Any,
    messages: List[ChatMessage],
    *,
    force_sync: bool = False,
    aggressive: bool = False,
) -> Optional[List[ChatMessage]]:
    """
    Aggressively shrink in-flight agent messages (mechanical, then optional LLM summary).
    Returns the new full message list, or None if nothing could be freed.
    """
    if not messages:
        return None

    system_msgs, convo = _split_system_and_conversation(list(messages))
    if len(convo) < 2:
        return None

    compressor = get_default_compressor()
    threshold_ratio = float(os.getenv("AION_CONTEXT_COMPRESS_MID_TURN_RATIO", "0.92"))
    max_prompt = compressor.max_prompt_tokens()
    target = int(max_prompt * (0.70 if aggressive else 0.82))

    keep_tools = 1 if aggressive else max(1, int(os.getenv("AION_MECHANICAL_COMPACT_KEEP_TOOLS", "3")))
    working_convo = list(convo)
    total_shrunk = 0

    for _ in range(8):
        stats = _estimate_prompt_total(agent, system_msgs + working_convo)
        if stats["total"] <= target:
            break
        new_convo, shrunk = mechanical_shrink_conversation(
            working_convo,
            keep_recent_tools=keep_tools,
        )
        if shrunk:
            working_convo = new_convo
            total_shrunk += shrunk
            continue
        if keep_tools > 0:
            keep_tools -= 1
            continue
        break

    stats = _estimate_prompt_total(agent, system_msgs + working_convo)
    if stats["total"] > max_prompt * 0.95 and force_sync:
        compacted = _sync_compact_head_tail(
            agent,
            system_msgs,
            working_convo,
            stats=stats,
            phase="emergency",
        )
        if compacted is not None:
            return compacted

    if total_shrunk == 0 and stats["total"] > target:
        return None
    return system_msgs + working_convo


def _sync_compact_head_tail(
    agent: Any,
    system_msgs: List[ChatMessage],
    convo: List[ChatMessage],
    *,
    stats: Dict[str, int],
    phase: str,
) -> Optional[List[ChatMessage]]:
    compressor = get_default_compressor()
    keep = compressor.keep_last
    from src.runtime.harness_flags import harness_v2_compaction
    from src.runtime.compaction import find_valid_cut_index

    if harness_v2_compaction():
        cut = find_valid_cut_index(convo, keep_last=keep)
        if cut < 0:
            return None
        head = convo[:cut]
        tail = convo[cut:]
    else:
        head = convo[:-keep] if len(convo) > keep else convo[:-1]
        tail = convo[-keep:] if len(convo) > keep else convo[-1:]

    transcript = "\n".join(f"{m.role}: {chat_message_text(m)[:3000]}" for m in head)
    if not transcript.strip():
        return None

    _emit_compacting(True, stats, phase=phase)
    from src.memory.context_compressor import compaction_summary_prompt
    from src.memory.llm_extract import complete_text_sync

    try:
        summary = complete_text_sync(
            compaction_summary_prompt(),
            transcript,
            max_tokens=int(os.getenv("AION_CONTEXT_COMPRESS_SUMMARY_MAX_TOKENS", "8192")),
            timeout=float(os.getenv("AION_CONTEXT_COMPRESS_MID_TURN_TIMEOUT", "90")),
        )
    except Exception as exc:
        logger.warning("%s compact LLM failed: %s", phase, exc)
        _emit_compacting(False, stats, phase=f"{phase}_failed")
        return None

    summary_msg = ChatMessage.from_user(
        format_compaction_block(summary or "", source_messages=len(head))
    )
    new_messages = system_msgs + [summary_msg] + list(tail)
    after_stats = _estimate_prompt_total(agent, new_messages)
    _emit_compacting(False, after_stats, phase=f"{phase}_done")
    return new_messages


def _emit_compacting(active: bool, stats: Dict[str, int], *, phase: str) -> None:
    if _turn_runtime is None:
        return
    rt = _turn_runtime.get()
    if not isinstance(rt, dict):
        return
    loop = rt.get("loop")
    queue = rt.get("queue")
    if not loop or not queue:
        return
    payload = {
        "type": "context_compacting",
        "active": active,
        "tokens": stats.get("total"),
        "trigger": stats.get("trigger"),
        "phase": phase,
        "mid_turn": True,
    }
    try:
        loop.call_soon_threadsafe(queue.put_nowait, payload)
    except Exception as exc:
        logger.debug("compact SSE emit failed: %s", exc)


def compact_agent_messages_in_place() -> bool:
    """
    Compatta i messaggi nello State Haystack corrente (sync, chiamabile dal thread tool/agent).
    Ritorna True se ha compattato.
    """
    if not mid_turn_compaction_enabled():
        return False
    if _agent_exec_ctx is None or _turn_runtime is None:
        return False
    exec_ctx = _agent_exec_ctx.get()
    rt = _turn_runtime.get()
    if exec_ctx is None or not isinstance(rt, dict):
        return False

    agent = rt.get("agent")
    if agent is None:
        return False

    state = getattr(exec_ctx, "state", None)
    if state is None:
        return False

    data = getattr(state, "_data", None) or getattr(state, "data", None)
    if not isinstance(data, dict):
        return False

    messages = data.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        return False

    now = time.monotonic()
    min_interval = float(os.getenv("AION_CONTEXT_COMPRESS_MID_TURN_MIN_SEC", "15"))
    last = float(rt.get("last_compact_at") or 0.0)
    if now - last < min_interval:
        return False

    extra = int(rt.get("extra_tokens") or 0)
    stats = _estimate_prompt_total(agent, messages, extra=extra)
    compressor = get_default_compressor()
    threshold_ratio = float(os.getenv("AION_CONTEXT_COMPRESS_MID_TURN_RATIO", "0.92"))
    mid_trigger = int(stats["max_prompt"] * threshold_ratio)

    logger.debug(
        f"THRESOLD RATIO {threshold_ratio} MID TRIGGER: {mid_trigger}   TOTAL {stats['total']} TRIGGER {compressor.compress_trigger_tokens()}"
    )

    if (
        stats["total"] < mid_trigger
        and stats["total"] < compressor.compress_trigger_tokens()
    ):
        return False

    system_msgs, convo = _split_system_and_conversation(list(messages))
    if len(convo) <= 1:
        return False

    if not mid_turn_sync_compaction_enabled():
        new_convo, shrunk = mechanical_shrink_conversation(convo)
        if shrunk:
            data["messages"] = system_msgs + new_convo
            rt["last_compact_at"] = now
            rt["extra_tokens"] = 0
            after_stats = _estimate_prompt_total(agent, data["messages"])
            logger.warning(
                "mid_turn_mechanical_compact session=%s tools_shrunk=%d tokens %d→%d",
                str(rt.get("session_id", ""))[:8],
                shrunk,
                stats["total"],
                after_stats["total"],
            )
            _mid_turn_debug_log(
                "mid_turn_mechanical_compact",
                {
                    "session_id": str(rt.get("session_id", ""))[:12],
                    "tools_shrunk": shrunk,
                    "tokens_before": stats["total"],
                    "tokens_after": after_stats["total"],
                },
            )
            return True
        logger.debug(
            "mid_turn compact skipped (sync disabled, mechanical noop); tokens=%s",
            stats["total"],
        )
        return False

    _emit_compacting(True, stats, phase="mid_turn")
    compacted = _sync_compact_head_tail(
        agent,
        system_msgs,
        convo,
        stats=stats,
        phase="mid_turn",
    )
    if compacted is None:
        new_convo, shrunk = mechanical_shrink_conversation(convo, keep_recent_tools=1)
        if not shrunk:
            _emit_compacting(False, stats, phase="mid_turn_failed")
            return False
        compacted = system_msgs + new_convo

    data["messages"] = compacted
    rt["last_compact_at"] = now
    rt["extra_tokens"] = 0

    after_stats = _estimate_prompt_total(agent, data["messages"])
    _emit_compacting(False, after_stats, phase="mid_turn_done")
    logger.warning(
        "mid_turn_compact session=%s messages %d→%d tokens %d→%d",
        str(rt.get("session_id", ""))[:8],
        len(messages),
        len(data["messages"]),
        stats["total"],
        after_stats["total"],
    )
    print(
        f">>> [CONTEXT mid-turn] session={str(rt.get('session_id', ''))[:8]} "
        f"tokens {stats['total']}→{after_stats['total']}",
        flush=True,
    )
    _mid_turn_debug_log(
        "mid_turn_compact_applied",
        {
            "session_id": str(rt.get("session_id", ""))[:12],
            "messages_before": len(messages),
            "messages_after": len(data["messages"]),
            "tokens_before": stats["total"],
            "tokens_after": after_stats["total"],
            "llm_steps_so_far": int(rt.get("llm_steps") or 0),
        },
    )

    summary_blocks = [
        m for m in data["messages"] if "compacted into the following" in chat_message_text(m)
    ]
    if summary_blocks:
        _schedule_db_persist(rt, summary_blocks[0], compressor.keep_last)
    return True


def _schedule_db_persist(
    rt: Dict[str, Any], summary_msg: ChatMessage, keep_last: int
) -> None:
    loop = rt.get("loop")
    session_id = rt.get("session_id")
    profile = rt.get("profile_name") or "default"
    if not loop or not session_id:
        return

    async def _persist() -> None:
        from src.api.history import history_manager

        try:
            await history_manager.persist_stm_compaction(
                session_id,
                profile_name=profile,
                summary_content=chat_message_text(summary_msg),
                keep_last_n=keep_last,
            )
        except Exception as exc:
            logger.warning("mid_turn persist failed: %s", exc)

    try:
        asyncio.run_coroutine_threadsafe(_persist(), loop)
    except Exception as exc:
        logger.debug("mid_turn persist schedule failed: %s", exc)


def _skip_mid_turn_compact_for_tool(tool_name: str, result: str) -> bool:
    """MemPalace tool outputs are small; compacting 600+ msg sessions blocks the agent thread for minutes."""
    if (tool_name or "").startswith("mempalace_"):
        return True
    return len(str(result or "")) < 800


def maybe_inject_max_steps_prompt() -> None:
    """Inject assistant warning when one LLM step remains before the hard agent limit."""
    if _agent_exec_ctx is None or _turn_runtime is None:
        return
    exec_ctx = _agent_exec_ctx.get()
    rt = _turn_runtime.get()
    if exec_ctx is None or not isinstance(rt, dict):
        return
    if rt.get("max_steps_injected"):
        return
    agent = rt.get("agent")
    max_steps = getattr(agent, "max_agent_steps", None) if agent else None
    if not max_steps:
        return
    try:
        cap = max(1, int(max_steps))
    except (TypeError, ValueError):
        return
    llm_steps = int(rt.get("llm_steps") or 0)
    if llm_steps < cap - 1:
        return
    state = getattr(exec_ctx, "state", None)
    if state is None:
        return
    messages = state.get("messages")
    if not isinstance(messages, list):
        return
    from src.runtime.doom_loop import MAX_STEPS_PROMPT

    messages.append(ChatMessage.from_system(MAX_STEPS_PROMPT))
    state["messages"] = messages
    rt["max_steps_injected"] = True


def maybe_compact_after_tool(*, tool_name: str, result: str) -> str:
    """Tronca output tool e, se serve, compatta lo state agent prima del prossimo LLM step."""
    out = truncate_tool_result(result, tool_name=tool_name)
    add_turn_token_estimate(count_tokens(out) + 128)
    try:
        maybe_inject_max_steps_prompt()
    except Exception as exc:
        logger.debug("max_steps inject failed: %s", exc)
    if mid_turn_compaction_enabled() and not _skip_mid_turn_compact_for_tool(
        tool_name, out
    ):
        try:
            compact_agent_messages_in_place()
        except Exception as exc:
            logger.warning("maybe_compact_after_tool failed: %s", exc)
    return out


def maybe_compact_after_reasoning(reasoning_piece: str) -> None:
    if not reasoning_piece:
        return
    add_turn_token_estimate(count_tokens(str(reasoning_piece)))
    if not mid_turn_reasoning_compaction_enabled():
        return
    if mid_turn_compaction_enabled():
        try:
            compact_agent_messages_in_place()
        except Exception as exc:
            logger.debug("compact after reasoning: %s", exc)


def install_agent_compaction_hooks() -> None:
    """Deprecated: usare ``AionAgent`` da ``src.runtime.aion_agent``. Ripara solo firme rotte."""
    try:
        from src.runtime.aion_agent import ensure_haystack_agent_signatures_valid

        ensure_haystack_agent_signatures_valid()
    except Exception as exc:
        logger.warning("install_agent_compaction_hooks: %s", exc)

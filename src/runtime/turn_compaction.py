"""Compattazione contesto durante un turno agent (dopo tool / ragionamento)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
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
# Shared by session_id — SSE stream loop (parent asyncio task) and agent.run (child task)
# mutate the same dict; contextvars alone do not propagate child → parent.
_TURN_RUNTIME_REGISTRY: Dict[str, Dict[str, Any]] = {}
_TURN_RUNTIME_LOCKS: Dict[str, threading.RLock] = {}


def _get_turn_lock(session_id: str) -> threading.RLock:
    sid = (session_id or "").strip()
    lock = _TURN_RUNTIME_LOCKS.get(sid)
    if lock is None:
        lock = threading.RLock()
        _TURN_RUNTIME_LOCKS[sid] = lock
    return lock


def _drop_turn_lock(session_id: str) -> None:
    sid = (session_id or "").strip()
    if sid:
        _TURN_RUNTIME_LOCKS.pop(sid, None)


try:
    import contextvars

    _agent_exec_ctx = contextvars.ContextVar("aion_agent_exec_ctx", default=None)
    _turn_runtime = contextvars.ContextVar("aion_turn_runtime", default=None)
except ImportError:
    pass


def context_budget_debug_enabled() -> bool:
    return _env_bool("AION_CONTEXT_BUDGET_DEBUG", "0")


def resolve_turn_runtime(session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Turn runtime dict for SSE budget — registry first, then task-local contextvar."""
    sid = (session_id or "").strip()
    if sid:
        rt = _TURN_RUNTIME_REGISTRY.get(sid)
        if isinstance(rt, dict):
            return rt
    if _turn_runtime is not None:
        rt = _turn_runtime.get()
        if isinstance(rt, dict):
            return rt
    if not sid:
        try:
            from src.runtime.context import get_current_session_id

            sid = (get_current_session_id() or "").strip()
            if sid:
                rt = _TURN_RUNTIME_REGISTRY.get(sid)
                if isinstance(rt, dict):
                    return rt
        except Exception:
            pass
    return None


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
    # Distinct from AION_WEB_FETCH_MAX_CHARS in web_providers.py (page extract limit).
    "web_fetch_page": "AION_TOOL_WEB_FETCH_MAX_CHARS",
    "web_search": "AION_TOOL_WEB_SEARCH_MAX_CHARS",
}

# Legacy env names (context-recovery rollout); prefer AION_TOOL_* above.
_PER_TOOL_CAP_LEGACY: Dict[str, str] = {
    "web_fetch_page": "AION_WEB_FETCH_MAX_CHARS",
    "web_search": "AION_WEB_SEARCH_MAX_CHARS",
}

_PER_TOOL_DEFAULTS: Dict[str, int] = {
    "web_fetch_page": 12000,
    "web_search": 12000,
}


def tool_result_max_chars_for(tool_name: str) -> int:
    key = (tool_name or "").strip().lower()
    for env_map in (_PER_TOOL_CAP_ENV, _PER_TOOL_CAP_LEGACY):
        env_name = env_map.get(key)
        if not env_name:
            continue
        try:
            default = str(_PER_TOOL_DEFAULTS.get(key, 6000))
            return max(500, int(os.getenv(env_name, default)))
        except ValueError:
            return _PER_TOOL_DEFAULTS.get(key, 6000)
    return tool_result_max_chars()


def _truncate_web_tool_json(text: str, tool_name: str, cap: int) -> Optional[str]:
    """Shrink web tool JSON/TOON without breaking structure (chat-ui parses JSON events)."""
    raw = str(text or "").strip()
    if raw.startswith("```toon"):
        key = (tool_name or "").strip().lower()
        if key == "web_search":
            from src.runtime.toon_encode import format_web_search_toon, parse_web_tool_payload

            data = parse_web_tool_payload(raw, key)
            if isinstance(data, dict):
                results = data.get("results")
                if isinstance(results, list):
                    budget = max(200, cap - 280)
                    per = max(40, budget // max(1, len(results)))
                    for row in results:
                        if not isinstance(row, dict):
                            continue
                        for field in ("snippet", "content", "description", "title"):
                            val = row.get(field)
                            if isinstance(val, str) and len(val) > per:
                                row[field] = val[:per] + "…"
                    out = format_web_search_toon(data)
                    while (
                        len(out) > cap
                        and isinstance(results, list)
                        and len(results) > 1
                    ):
                        results.pop()
                        data["results"] = results
                        out = format_web_search_toon(data)
                    if len(out) <= cap:
                        return out
        note = "\n[AION: truncated for context budget]"
        max_body = max(200, cap - 120)
        if len(raw) <= cap:
            return raw
        # Keep TOON header lines; trim trailing text block.
        lines = raw.splitlines()
        head = []
        for line in lines:
            if line.startswith("text:") or line.strip() == "text: |":
                break
            head.append(line)
        body_budget = max(
            120, cap - sum(len(head_line) + 1 for head_line in head) - len(note) - 8
        )
        trimmed = "\n".join(
            head + ["text: |", raw[raw.find("text:") :][:body_budget] + note, "```"]
        )
        return trimmed[:cap]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    note = " [AION: truncated for context budget]"
    key = (tool_name or "").strip().lower()

    if key == "web_fetch_page":
        body = data.get("text")
        if isinstance(body, str) and body:
            max_body = max(200, cap - 420)
            if len(body) > max_body:
                data["text"] = body[:max_body] + note
        out = json.dumps(data, ensure_ascii=False)
        if len(out) <= cap:
            return out
        short = dict(data)
        short["text"] = str(data.get("text", ""))[: max(120, cap - 280)] + note
        short.pop("hint", None)
        return json.dumps(short, ensure_ascii=False)

    if key == "web_search":
        results = data.get("results")
        if isinstance(results, list):
            budget = max(200, cap - 280)
            per = max(60, budget // max(1, len(results)))
            for row in results:
                if not isinstance(row, dict):
                    continue
                for field in ("snippet", "content", "description"):
                    val = row.get(field)
                    if isinstance(val, str) and len(val) > per:
                        row[field] = val[:per] + "…"
        out = json.dumps(data, ensure_ascii=False)
        while len(out) > cap and isinstance(results, list) and results:
            results.pop()
            out = json.dumps(data, ensure_ascii=False)
        return out

    return None


def truncate_tool_result(result: str, *, tool_name: str = "") -> str:
    """Riduce output tool enormi (es. 200 email) prima che entrino nel contesto Haystack."""
    text = str(result or "")
    cap = tool_result_max_chars_for(tool_name)
    if len(text) <= cap:
        return text
    key = (tool_name or "").strip().lower()
    if key in ("web_fetch_page", "web_search"):
        compact = _truncate_web_tool_json(text, key, cap)
        if compact is not None and len(compact) <= cap:
            return compact
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
    preflight_messages: Optional[List[ChatMessage]] = None,
) -> None:
    sid = (session_id or "").strip()
    with _get_turn_lock(sid):
        existing = _TURN_RUNTIME_REGISTRY.get(sid) if sid else None
        if isinstance(existing, dict):
            rt = existing
            rt.update(
                {
                    "session_id": sid,
                    "loop": loop,
                    "queue": queue,
                    "stop_event": stop_event,
                    "agent": agent,
                    "profile_name": profile_name,
                    "user_id": user_id,
                    "preflight_messages": preflight_messages,
                }
            )
            if preflight_messages is not None and not rt.get("live_messages"):
                rt["live_messages"] = list(preflight_messages)
        else:
            rt = {
                "session_id": sid,
                "loop": loop,
                "queue": queue,
                "stop_event": stop_event,
                "agent": agent,
                "profile_name": profile_name,
                "user_id": user_id,
                "preflight_messages": preflight_messages,
                "live_messages": list(preflight_messages or []),
                "extra_tokens": 0,
                "last_compact_at": 0.0,
                "llm_steps": 0,
                "tool_error_recovery_attempts": 0,
                "context_recovery_attempts": 0,
            }
            if sid:
                _TURN_RUNTIME_REGISTRY[sid] = rt
    if _turn_runtime is not None:
        _turn_runtime.set(rt)
    try:
        from src.runtime.tool_error_recovery import reset_tracker

        reset_tracker(session_id)
    except Exception:
        pass


def bump_llm_step() -> int:
    rt = resolve_turn_runtime()
    if not isinstance(rt, dict):
        return 0
    n = int(rt.get("llm_steps") or 0) + 1
    rt["llm_steps"] = n
    return n


def get_llm_step_count() -> int:
    rt = resolve_turn_runtime()
    if not isinstance(rt, dict):
        return 0
    return int(rt.get("llm_steps") or 0)


def _mid_turn_debug_log(message: str, data: Dict[str, Any]) -> None:
    from src.runtime.turn_diagnostics import agent_debug_log

    agent_debug_log("H4", "turn_compaction:compact", message, data)


def _messages_from_exec_ctx(exec_ctx: Any = None) -> List[ChatMessage]:
    if exec_ctx is None:
        if _agent_exec_ctx is None:
            return []
        exec_ctx = _agent_exec_ctx.get()
    if exec_ctx is None:
        return []
    state = getattr(exec_ctx, "state", None)
    if state is None:
        return []
    data = getattr(state, "_data", None) or getattr(state, "data", None)
    if not isinstance(data, dict):
        return []
    messages = data.get("messages")
    if not isinstance(messages, list):
        return []
    return messages


def sync_live_turn_messages(session_id: Optional[str] = None) -> bool:
    """Copy Haystack State messages into turn_runtime (visible across asyncio tasks)."""
    messages = _messages_from_exec_ctx()
    if not messages:
        return False
    rt = resolve_turn_runtime(session_id)
    if not isinstance(rt, dict):
        return False
    sid = str(rt.get("session_id") or session_id or "").strip()
    with _get_turn_lock(sid):
        rt["live_messages"] = list(messages)
    return True


def get_turn_messages(session_id: Optional[str] = None) -> List[ChatMessage]:
    """Live Haystack State messages during agent.run (mid-turn budget)."""
    messages = _messages_from_exec_ctx()
    if messages:
        rt = resolve_turn_runtime(session_id)
        if isinstance(rt, dict):
            rt["live_messages"] = list(messages)
        return messages
    rt = resolve_turn_runtime(session_id)
    if not isinstance(rt, dict):
        return []
    live = rt.get("live_messages")
    if isinstance(live, list) and live:
        return live
    pref = rt.get("preflight_messages")
    if isinstance(pref, list) and pref:
        return pref
    return []


def try_build_context_budget_event(
    *,
    phase: str = "mid_turn",
    session_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Build context_budget SSE payload from live agent state (or preflight fallback)."""
    rt = resolve_turn_runtime(session_id)
    if not isinstance(rt, dict):
        return None
    agent = rt.get("agent")
    if agent is None:
        return None
    sid = (session_id or str(rt.get("session_id") or "")).strip()
    messages = get_turn_messages(sid or None)
    if not messages:
        pref = rt.get("preflight_messages")
        if isinstance(pref, list) and pref:
            messages = pref
    if not messages:
        if context_budget_debug_enabled():
            logger.warning(
                "context_budget skip phase=%s session=%s: no messages",
                phase,
                sid[:12] if sid else "?",
            )
        return None
    from src.memory.context_compressor import build_context_budget_event

    payload = build_context_budget_event(agent, messages, phase=phase)
    payload = _merge_budget_deltas_into_payload(payload, rt)
    if context_budget_debug_enabled():
        web_tok = sum(
            p.get("tokens", 0)
            for p in (payload.get("parts") or [])
            if p.get("key") in ("web_tools", "tool_results")
        )
        logger.info(
            "context_budget phase=%s session=%s msgs=%s total=%s pct=%s web+tools=%s",
            phase,
            sid[:12] if sid else "?",
            payload.get("message_count"),
            payload.get("total"),
            payload.get("pct"),
            web_tok,
        )
    return payload


def emit_context_budget_sse(
    *, phase: str = "mid_turn", session_id: Optional[str] = None
) -> None:
    rt = resolve_turn_runtime(session_id)
    if not isinstance(rt, dict):
        return
    loop = rt.get("loop")
    queue = rt.get("queue")
    if not loop or not queue:
        return
    sid = (session_id or str(rt.get("session_id") or "")).strip() or None
    payload = try_build_context_budget_event(phase=phase, session_id=sid)
    if not payload:
        return
    try:
        loop.call_soon_threadsafe(queue.put_nowait, payload)
    except Exception as exc:
        logger.debug("context_budget SSE emit failed: %s", exc)


def set_agent_execution_context(exec_ctx: Any) -> None:
    if _agent_exec_ctx is not None:
        _agent_exec_ctx.set(exec_ctx)
    messages = _messages_from_exec_ctx(exec_ctx)
    if messages:
        rt = resolve_turn_runtime()
        if isinstance(rt, dict):
            sid = str(rt.get("session_id") or "").strip()
            with _get_turn_lock(sid):
                rt["live_messages"] = list(messages)


def clear_agent_execution_context() -> None:
    if _agent_exec_ctx is not None:
        _agent_exec_ctx.set(None)


def clear_turn_runtime(session_id: Optional[str] = None) -> None:
    sid = (session_id or "").strip()
    if not sid:
        rt = resolve_turn_runtime()
        if isinstance(rt, dict):
            sid = str(rt.get("session_id") or "").strip()
    if sid:
        with _get_turn_lock(sid):
            _TURN_RUNTIME_REGISTRY.pop(sid, None)
        _drop_turn_lock(sid)
    if _turn_runtime is not None:
        _turn_runtime.set(None)
    clear_agent_execution_context()


def add_turn_token_estimate(delta: int, *, bucket: str = "tool_results") -> None:
    rt = resolve_turn_runtime()
    if not isinstance(rt, dict):
        return
    d = max(0, int(delta))
    if d <= 0:
        return
    sid = str(rt.get("session_id") or "").strip()
    with _get_turn_lock(sid):
        bd = rt.setdefault("budget_delta", {})
        key = (bucket or "tool_results").strip() or "tool_results"
        bd[key] = int(bd.get(key) or 0) + d
        rt["extra_tokens"] = int(rt.get("extra_tokens") or 0) + d


def record_pi_context_delta(
    session_id: str,
    bucket: str,
    delta: int,
) -> None:
    """Track Pi long-run stream tokens (reasoning/assistant) for context budget bar."""
    rt = resolve_turn_runtime(session_id)
    if not isinstance(rt, dict):
        return
    add_turn_token_estimate(delta, bucket=bucket)


def _merge_budget_deltas_into_payload(
    payload: Dict[str, Any], rt: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge mid-turn token deltas into parts so the bar matches total/pct."""
    from src.memory.context_compressor import _CONTEXT_BUDGET_PART_ORDER

    bd: Dict[str, int] = dict(rt.get("budget_delta") or {})
    legacy_extra = int(rt.get("extra_tokens") or 0)
    accounted = sum(int(v) for v in bd.values())
    if legacy_extra > accounted:
        bd["tool_results"] = int(bd.get("tool_results") or 0) + (
            legacy_extra - accounted
        )
    if not bd:
        return payload

    parts_by_key: Dict[str, Dict[str, Any]] = {
        str(p.get("key")): dict(p) for p in (payload.get("parts") or []) if p.get("key")
    }
    for key, tok in bd.items():
        if tok <= 0:
            continue
        if key in parts_by_key:
            parts_by_key[key]["tokens"] = (
                int(parts_by_key[key].get("tokens") or 0) + tok
            )
        else:
            parts_by_key[key] = {"key": key, "tokens": tok, "pct": 0.0}

    max_prompt = max(int(payload.get("max_prompt") or 1), 1)
    ordered: List[Dict[str, Any]] = []
    total = 0
    seen: set[str] = set()
    for key in _CONTEXT_BUDGET_PART_ORDER:
        if key not in parts_by_key:
            continue
        p = parts_by_key[key]
        tok = int(p.get("tokens") or 0)
        if tok <= 0:
            continue
        p["pct"] = round(tok * 100.0 / max_prompt, 1)
        ordered.append(p)
        total += tok
        seen.add(key)
    for key, p in parts_by_key.items():
        if key in seen:
            continue
        tok = int(p.get("tokens") or 0)
        if tok <= 0:
            continue
        p["pct"] = round(tok * 100.0 / max_prompt, 1)
        ordered.append(p)
        total += tok

    payload["parts"] = ordered
    payload["total"] = total
    payload["pct"] = round(total * 100.0 / max_prompt, 1)
    return payload


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
    tool_indices = [i for i, m in enumerate(convo) if _message_role_str(m) == "tool"]
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

    keep_tools = (
        1
        if aggressive
        else max(1, int(os.getenv("AION_MECHANICAL_COMPACT_KEEP_TOOLS", "3")))
    )
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


def _append_ledger_offload_context(transcript: str, session_id: str) -> str:
    """Append ledger/offload pointers to mid-turn compaction transcript (mirrors policy.py)."""
    from src.runtime.tool_ledger import (
        ledger_summary_lines,
        offload_paths_for_session,
        render_ledger_table,
        tool_ledger_enabled,
    )

    sid = (session_id or "").strip()
    if not sid:
        return transcript
    ledger = ""
    if tool_ledger_enabled():
        ledger = render_ledger_table(sid) or ""
        offload_block = "\n".join(offload_paths_for_session(sid)[:40])
        if offload_block:
            ledger = f"{ledger}\n\n<offloaded-results>\n{offload_block}\n</offloaded-results>"
        trace_lines = ledger_summary_lines(sid)
        if trace_lines:
            ledger = (
                f"{ledger}\n\n<tool-trace>\n"
                + "\n".join(trace_lines)
                + "\n</tool-trace>"
            )
    if not ledger:
        return transcript
    cap = 12000
    body = transcript[:cap]
    if len(transcript) > cap:
        body += "\n...[transcript truncated]"
    return f"{body}\n\n{ledger[:4000]}"


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

    session_id = ""
    try:
        from src.runtime.context import get_current_session_id

        session_id = (get_current_session_id() or "").strip()
    except Exception:
        pass
    transcript = _append_ledger_offload_context(transcript, session_id)

    _emit_compacting(True, stats, phase=phase)
    from src.memory.context_compressor import compaction_summary_prompt
    from src.memory.llm_extract import complete_text_sync

    try:
        summary = complete_text_sync(
            compaction_summary_prompt(),
            transcript,
            max_tokens=int(
                os.getenv("AION_CONTEXT_COMPRESS_SUMMARY_MAX_TOKENS", "8192")
            ),
            timeout=float(os.getenv("AION_CONTEXT_COMPRESS_MID_TURN_TIMEOUT", "90")),
        )
    except Exception as exc:
        logger.warning("%s compact LLM failed: %s", phase, exc)
        _emit_compacting(False, stats, phase=f"{phase}_failed")
        return None

    logger.info(
        "mid_turn_compaction session=%s phase=%s archived_head_msgs=%s tokens_before=%s ledger_included=%s",
        session_id[:12] if session_id else "?",
        phase,
        len(head),
        stats.get("total"),
        bool(session_id),
    )
    summary_msg = ChatMessage.from_user(
        format_compaction_block(summary or "", source_messages=len(head))
    )
    new_messages = system_msgs + [summary_msg] + list(tail)
    after_stats = _estimate_prompt_total(agent, new_messages)
    _emit_compacting(False, after_stats, phase=f"{phase}_done")
    return new_messages


def _emit_compacting(active: bool, stats: Dict[str, int], *, phase: str) -> None:
    rt = resolve_turn_runtime()
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
    if not active:
        emit_context_budget_sse(phase=phase)


def compact_agent_messages_in_place() -> bool:
    """
    Compatta i messaggi nello State Haystack corrente (sync, chiamabile dal thread tool/agent).
    Ritorna True se ha compattato.
    """
    if not mid_turn_compaction_enabled():
        return False
    if _agent_exec_ctx is None:
        return False
    exec_ctx = _agent_exec_ctx.get()
    rt = resolve_turn_runtime()
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
            rt["live_messages"] = data["messages"]
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
    rt["live_messages"] = data["messages"]

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
        m
        for m in data["messages"]
        if "compacted into the following" in chat_message_text(m)
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
    if _agent_exec_ctx is None:
        return
    exec_ctx = _agent_exec_ctx.get()
    rt = resolve_turn_runtime()
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


def _web_tool_compact_threshold(agent: Any) -> int:
    try:
        ratio = float(os.getenv("AION_WEB_TOOL_COMPACT_RATIO", "0.55"))
    except ValueError:
        ratio = 0.55
    try:
        max_prompt = int(
            getattr(agent, "max_prompt_tokens", None)
            or os.getenv("AION_CONTEXT_WINDOW", "131072")
        )
    except ValueError:
        max_prompt = 131072
    return int(max_prompt * ratio)


def _maybe_early_web_tool_compact(
    agent: Any,
    data: Dict[str, Any],
    messages: List[ChatMessage],
    rt: Dict[str, Any],
) -> bool:
    """Mechanical shrink when many web tools fill context before global 92% threshold."""
    try:
        after_n = max(2, int(os.getenv("AION_WEB_TOOL_COMPACT_AFTER", "4")))
    except ValueError:
        after_n = 4
    web_count = int(rt.get("web_tool_calls") or 0)
    if web_count < after_n:
        return False

    system_msgs, convo = _split_system_and_conversation(list(messages))
    if len(convo) <= 1:
        return False

    extra = int(rt.get("extra_tokens") or 0)
    stats = _estimate_prompt_total(agent, messages, extra=extra)
    if stats["total"] < _web_tool_compact_threshold(agent):
        return False

    keep = max(1, int(os.getenv("AION_MECHANICAL_COMPACT_KEEP_TOOLS", "2")))
    new_convo, shrunk = mechanical_shrink_conversation(convo, keep_recent_tools=keep)
    if not shrunk:
        return False

    data["messages"] = system_msgs + new_convo
    rt["last_compact_at"] = time.monotonic()
    rt["extra_tokens"] = 0
    rt["live_messages"] = data["messages"]
    after_stats = _estimate_prompt_total(agent, data["messages"])
    logger.warning(
        "web_tool_early_compact session=%s web_calls=%d tools_shrunk=%d tokens %d→%d",
        str(rt.get("session_id", ""))[:8],
        web_count,
        shrunk,
        stats["total"],
        after_stats["total"],
    )
    _mid_turn_debug_log(
        "web_tool_early_compact",
        {
            "session_id": str(rt.get("session_id", ""))[:12],
            "web_tool_calls": web_count,
            "tools_shrunk": shrunk,
            "tokens_before": stats["total"],
            "tokens_after": after_stats["total"],
        },
    )
    return True


def maybe_compact_after_tool(
    *,
    tool_name: str,
    result: str,
    arguments: Optional[Dict[str, Any]] = None,
) -> str:
    """Tronca output tool e, se serve, compatta lo state agent prima del prossimo LLM step."""
    rt = resolve_turn_runtime()
    session_id = str(rt.get("session_id") or "") if isinstance(rt, dict) else ""
    from src.runtime.tool_offload import process_tool_result_for_context

    out, _details = process_tool_result_for_context(
        result,
        session_id=session_id,
        tool_name=tool_name,
        arguments=arguments,
    )
    tname = (tool_name or "").strip().lower()
    bucket = (
        "web_tools"
        if tname in ("web_search", "web_fetch_page")
        else "skills"
        if tname in ("skill_view", "skill_search", "skill_list")
        else "tool_results"
    )
    add_turn_token_estimate(count_tokens(out) + 128, bucket=bucket)
    if tname in ("web_search", "web_fetch_page"):
        rt = resolve_turn_runtime()
        if isinstance(rt, dict):
            rt["web_tool_calls"] = int(rt.get("web_tool_calls") or 0) + 1
    try:
        maybe_inject_max_steps_prompt()
    except Exception as exc:
        logger.debug("max_steps inject failed: %s", exc)
    if mid_turn_compaction_enabled() and not _skip_mid_turn_compact_for_tool(
        tool_name, out
    ):
        try:
            if tname in ("web_search", "web_fetch_page"):
                exec_ctx = _agent_exec_ctx.get() if _agent_exec_ctx else None
                state = getattr(exec_ctx, "state", None) if exec_ctx else None
                data = (
                    getattr(state, "_data", None) or getattr(state, "data", None)
                    if state
                    else None
                )
                messages = data.get("messages") if isinstance(data, dict) else None
                agent = (rt or {}).get("agent") if isinstance(rt, dict) else None
                if (
                    isinstance(rt, dict)
                    and isinstance(data, dict)
                    and isinstance(messages, list)
                    and agent is not None
                    and _maybe_early_web_tool_compact(agent, data, messages, rt)
                ):
                    sync_live_turn_messages()
                    emit_context_budget_sse(phase="web_tool_compact")
                    return out
            compact_agent_messages_in_place()
        except Exception as exc:
            logger.warning("maybe_compact_after_tool failed: %s", exc)
    sync_live_turn_messages()
    emit_context_budget_sse(phase="tool")
    return out


def maybe_compact_after_reasoning(reasoning_piece: str) -> None:
    if not reasoning_piece:
        return
    add_turn_token_estimate(count_tokens(str(reasoning_piece)), bucket="reasoning")
    emit_context_budget_sse(phase="reasoning")
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

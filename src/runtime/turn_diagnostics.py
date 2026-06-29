"""Turn outcome classification and JSONL diagnostics for silent / empty agent turns."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aion.turn.diagnostics")

_REPO_ROOT = Path(__file__).resolve().parents[2]


def diagnostics_enabled() -> bool:
    return os.getenv("AION_TURN_DIAGNOSTICS", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def debug_log_path() -> Path:
    explicit = (os.getenv("AION_AGENT_DEBUG_LOG") or "").strip()
    if explicit:
        return Path(explicit)
    return _REPO_ROOT / "data" / "diagnostics" / "agent-debug.jsonl"


def turn_log_path() -> Path:
    explicit = (os.getenv("AION_TURN_DIAGNOSTICS_LOG") or "").strip()
    if explicit:
        return Path(explicit)
    return _REPO_ROOT / "data" / "diagnostics" / "turns.jsonl"


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    if not diagnostics_enabled():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": int(time.time() * 1000), **record}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("turn diagnostics write failed: %s", exc)


def agent_debug_log(
    hypothesis_id: str,
    location: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    run_id: str = "turn",
) -> None:
    append_jsonl(
        debug_log_path(),
        {
            "kind": "agent_debug",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
        },
    )


def _summarize_messages(new_messages: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not isinstance(new_messages, list):
        return out
    for msg in new_messages[:20]:
        role = getattr(msg, "role", None)
        role_s = role.value if hasattr(role, "value") else str(role or "?")
        tc = getattr(msg, "tool_calls", None) or []
        tool_names = []
        if tc:
            for t in tc[:5]:
                tool_names.append(getattr(t, "tool_name", None) or str(t))
        text = ""
        try:
            from src.haystack_chat import chat_message_text

            text = (chat_message_text(msg) or "")[:120]
        except Exception:
            text = str(getattr(msg, "content", ""))[:120]
        out.append(
            {
                "role": role_s,
                "tools": ",".join(tool_names) if tool_names else "",
                "preview": text.replace("\n", " "),
            }
        )
    return out


def classify_turn_outcome(
    *,
    session_id: str,
    profile: str,
    stop_reason: str,
    final_text: str,
    full_reasoning: str,
    tool_calls_count: int,
    tool_events_count: int,
    new_messages: Any,
    context_stats: Optional[Dict[str, Any]] = None,
    max_agent_steps: Optional[int] = None,
    llm_steps: int = 0,
    plan_intercepts: int = 0,
) -> Dict[str, Any]:
    """Return outcome code, metrics, and optional user-facing warning (Italian)."""
    final_len = len((final_text or "").strip())
    reasoning_len = len((full_reasoning or "").strip())
    msg_summary = _summarize_messages(new_messages)
    new_msg_count = len(new_messages) if isinstance(new_messages, list) else 0
    assistant_text_msgs = sum(
        1
        for m in msg_summary
        if m.get("role") == "assistant" and m.get("preview") and not m.get("tools")
    )
    tool_only_assistant = sum(
        1 for m in msg_summary if m.get("role") == "assistant" and m.get("tools")
    )

    code = "ok"
    suggested_final_text: Optional[str] = None
    if final_len == 0 and reasoning_len > 200 and tool_calls_count == 0:
        code = "reasoning_only_no_answer"
    elif final_len == 0 and plan_intercepts > 0 and tool_calls_count > 0:
        code = "plan_created"
        suggested_final_text = (
            "I created the execution plan in the **Plan** sidebar. "
            "Review the tasks, edit if needed, and approve to start execution."
        )
    elif final_len == 0 and tool_calls_count > 0:
        code = "tools_without_final_answer"
    elif final_len == 0 and new_msg_count > 0 and assistant_text_msgs == 0:
        code = "persisted_no_visible_text"
    elif final_len == 0:
        code = "empty_final"
    elif stop_reason not in ("completed", ""):
        code = f"stopped_{stop_reason}"

    ctx_total = (context_stats or {}).get("total")
    ctx_msg = (context_stats or {}).get("message_count") or (context_stats or {}).get("msg")

    warning: Optional[str] = None
    if code != "ok" and code != "plan_created":
        parts = [
            "The turn ended without a complete text reply in chat.",
        ]
        if code == "tools_without_final_answer":
            parts.append(
                f"The agent ran {tool_calls_count} tool calls but did not write a final summary."
            )
        elif code == "reasoning_only_no_answer":
            parts.append(
                "Internal reasoning was generated but no visible reply text."
            )
        elif code == "persisted_no_visible_text":
            parts.append(
                f"Persisted {new_msg_count} messages (e.g. tool-only) with no final assistant text."
            )
        else:
            parts.append(f"Outcome: {code}.")

        if ctx_msg and int(ctx_msg) > 100:
            parts.append(
                f"Very long session (~{ctx_msg} messages): start a new chat or compact history."
            )
        if ctx_total and int(ctx_total) > 20000:
            parts.append(
                f"Estimated context ~{ctx_total} tokens): the model may truncate or skip the final round."
            )
        if max_agent_steps and llm_steps >= int(max_agent_steps):
            parts.append(
                f"Agent step limit reached ({llm_steps}/{max_agent_steps})."
            )
        parts.append(
            "See `data/diagnostics/turns.jsonl` for details. "
            "For structured MemPalace import, retry in a new chat or run "
            "`python scripts/bootstrap_db_navigation_mempalace.py --project <slug>`."
        )
        warning = " ".join(parts)

    return {
        "code": code,
        "session_id": session_id,
        "profile": profile,
        "stop_reason": stop_reason,
        "final_text_len": final_len,
        "reasoning_len": reasoning_len,
        "tool_calls": tool_calls_count,
        "tool_events": tool_events_count,
        "new_messages_count": new_msg_count,
        "assistant_text_msgs": assistant_text_msgs,
        "tool_only_assistant": tool_only_assistant,
        "message_summary": msg_summary,
        "context": context_stats or {},
        "max_agent_steps": max_agent_steps,
        "llm_steps": llm_steps,
        "user_visible_warning": warning,
        "suggested_final_text": suggested_final_text,
    }


def record_turn_outcome(record: Dict[str, Any]) -> None:
    append_jsonl(turn_log_path(), {"kind": "turn_outcome", **record})
    code = record.get("code", "ok")
    if code != "ok":
        logger.warning(
            "turn_outcome session=%s code=%s final_len=%s reasoning_len=%s tools=%s stop=%s msgs=%s",
            str(record.get("session_id", ""))[:12],
            code,
            record.get("final_text_len"),
            record.get("reasoning_len"),
            record.get("tool_calls"),
            record.get("stop_reason"),
            record.get("new_messages_count"),
        )

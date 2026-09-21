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


def _effort_label(effort: Optional[str]) -> str:
    raw = (effort or "").strip().lower()
    if raw in ("off", ""):
        return "disattivato"
    if raw == "min":
        return "minimo"
    if raw == "medium":
        return "medio"
    if raw == "max":
        return "massimo"
    return raw or "—"


def _build_user_warning(
    *,
    code: str,
    stop_reason: str,
    tool_calls_count: int,
    new_msg_count: int,
    ctx_msg: Any,
    ctx_total: Any,
    max_agent_steps: Optional[int],
    llm_steps: int,
    reasoning_effort: Optional[str],
    max_reasoning_chars: Optional[int],
    max_reasoning_events: Optional[int],
    reasoning_len: int,
) -> str:
    effort = _effort_label(reasoning_effort)
    limits = ""
    if max_reasoning_chars or max_reasoning_events:
        limits = (
            f" (soglia attiva: ~{max_reasoning_chars or '—'} caratteri"
            f" / {max_reasoning_events or '—'} chunk di reasoning nel primo step LLM)"
        )

    if code == "reasoning_budget_no_answer":
        return (
            f"Il turno si è interrotto perché il modello ha superato il budget di ragionamento "
            f"con Thinking **{effort}**{limits} prima di scrivere una risposta visibile in chat. "
            f"Il blocco «Ragionamento» contiene solo il pensiero interno (~{reasoning_len} caratteri). "
            f"Prova: disattiva Thinking dal menu **+**, abbassa il livello, scrivi «Continua» "
            f"per riprendere, o riduci i limiti in Tuning e parametri (sidebar)."
        )
    if code == "reasoning_only_no_answer":
        return (
            f"Il modello ha generato solo ragionamento interno (~{reasoning_len} caratteri) "
            f"senza produrre testo di risposta in chat (Thinking: **{effort}**). "
            f"Riprova con un messaggio più breve, disattiva Thinking dal menu **+**, "
            f"o chiedi esplicitamente una risposta finale."
        )
    if code == "tools_without_final_answer":
        if stop_reason == "reasoning_budget":
            base = (
                f"Il turno è stato interrotto dal guard-rail sul reasoning (Thinking **{effort}**)"
                f"{limits}. L'agente ha eseguito {tool_calls_count} chiamate tool ma non ha "
                f"scritto un riepilogo finale. Usa «Continua» o chiedi un riepilogo dei risultati."
            )
        else:
            base = (
                f"L'agente ha eseguito {tool_calls_count} chiamate tool ma non ha scritto "
                f"un riepilogo finale in chat."
            )
        if ctx_msg and int(ctx_msg) > 100:
            base += (
                f" Sessione molto lunga (~{ctx_msg} messaggi): prova una nuova chat "
                f"o compatta la cronologia."
            )
        if ctx_total and int(ctx_total) > 20000:
            base += f" Contesto stimato ~{ctx_total} token: il modello può troncare l'ultimo round."
        return base
    if code == "persisted_no_visible_text":
        return (
            f"Il turno ha salvato {new_msg_count} messaggi (es. solo tool) "
            f"senza testo assistente finale visibile."
        )
    if code == "empty_final":
        if stop_reason == "reasoning_budget":
            return (
                f"Risposta vuota: interrotto dal budget di reasoning (Thinking **{effort}**)"
                f"{limits}."
            )
        return "Il turno è terminato senza testo di risposta in chat."

    parts = [f"Il turno non ha prodotto una risposta completa in chat (esito: {code})."]
    if stop_reason and stop_reason not in ("completed", ""):
        parts.append(f"Motivo interno: {stop_reason}.")
    if ctx_msg and int(ctx_msg) > 100:
        parts.append(
            f"Sessione molto lunga (~{ctx_msg} messaggi): prova una nuova chat o compatta la cronologia."
        )
    if ctx_total and int(ctx_total) > 20000:
        parts.append(
            f"Contest stimato ~{ctx_total} token: il modello può troncare l'ultimo round."
        )
    if max_agent_steps and llm_steps >= int(max_agent_steps):
        parts.append(
            f"Raggiunto il limite di step agente ({llm_steps}/{max_agent_steps})."
        )
    msg = " ".join(parts)
    if ctx_msg and int(ctx_msg) > 100:
        msg += (
            f" Sessione molto lunga (~{ctx_msg} messaggi): prova una nuova chat "
            f"o compatta la cronologia."
        )
    if ctx_total and int(ctx_total) > 20000:
        msg += f" Contesto stimato ~{ctx_total} token: il modello può troncare l'ultimo round."
    return msg


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
    reasoning_effort: Optional[str] = None,
    max_reasoning_chars: Optional[int] = None,
    max_reasoning_events: Optional[int] = None,
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

    # User-initiated cancel: never surface a scary warning to the chat UI.
    if stop_reason and "cancel" in stop_reason.lower():
        return {
            "code": "user_cancelled",
            "session_id": session_id,
            "profile": profile,
            "stop_reason": stop_reason,
            "final_text_len": final_len,
            "reasoning_len": reasoning_len,
            "tool_calls": tool_calls_count,
            "tool_events": tool_events_count,
            "new_messages_count": len(new_messages)
            if isinstance(new_messages, list)
            else 0,
            "assistant_text_msgs": 0,
            "tool_only_assistant": 0,
            "message_summary": [],
            "context": context_stats or {},
            "max_agent_steps": max_agent_steps,
            "llm_steps": llm_steps,
            "user_visible_warning": None,
            "suggested_final_text": None,
        }

    code = "ok"
    suggested_final_text: Optional[str] = None
    if final_len == 0 and reasoning_len > 200 and tool_calls_count == 0:
        if stop_reason == "reasoning_budget":
            code = "reasoning_budget_no_answer"
        else:
            code = "reasoning_only_no_answer"
    elif final_len == 0 and plan_intercepts > 0 and tool_calls_count > 0:
        code = "plan_created"
        suggested_final_text = (
            "I created the execution plan in the **Plan** sidebar. "
            "Review the tasks, edit if needed, and approve to start execution."
        )
    elif final_len == 0 and tool_calls_count > 0:
        code = "tools_without_final_answer"
        if stop_reason == "reasoning_budget":
            suggested_final_text = (
                "Il turno è stato interrotto dal guard-rail sul reasoning (troppi chunk "
                "di pensiero in un singolo step LLM). I tool sono stati eseguiti: "
                "riprova con «Continua» o chiedi un riepilogo dei risultati già raccolti."
            )
    elif final_len == 0 and new_msg_count > 0 and assistant_text_msgs == 0:
        code = "persisted_no_visible_text"
    elif final_len == 0:
        code = "empty_final"
    elif stop_reason not in ("completed", ""):
        code = f"stopped_{stop_reason}"

    ctx_total = (context_stats or {}).get("total")
    ctx_msg = (context_stats or {}).get("message_count") or (context_stats or {}).get(
        "msg"
    )

    details = {
        "reasoning_effort": (reasoning_effort or "").strip().lower() or None,
        "max_reasoning_chars": max_reasoning_chars,
        "max_reasoning_events": max_reasoning_events,
        "reasoning_len": reasoning_len,
        "stop_reason": stop_reason or None,
        "tool_calls": tool_calls_count,
    }

    warning: Optional[str] = None
    if code != "ok" and code != "plan_created":
        warning = _build_user_warning(
            code=code,
            stop_reason=stop_reason,
            tool_calls_count=tool_calls_count,
            new_msg_count=new_msg_count,
            ctx_msg=ctx_msg,
            ctx_total=ctx_total,
            max_agent_steps=max_agent_steps,
            llm_steps=llm_steps,
            reasoning_effort=reasoning_effort,
            max_reasoning_chars=max_reasoning_chars,
            max_reasoning_events=max_reasoning_events,
            reasoning_len=reasoning_len,
        )

    return {
        "code": code,
        "details": details,
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


def turn_debug_verbose() -> bool:
    return os.getenv("AION_TURN_DEBUG_VERBOSE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def log_turn_stop(
    session_id: str,
    reason: str,
    *,
    location: str = "",
    **metrics: Any,
) -> None:
    """Structured log + JSONL when diagnostics enabled — every hard/agent stop."""
    sid = (session_id or "")[:12]
    msg = (
        f"turn_stop session={sid} reason={reason} location={location or '?'}"
        f" metrics={json.dumps(metrics, default=str)[:2000]}"
    )
    logger.warning(msg)
    if turn_debug_verbose():
        logger.info(msg)
    append_jsonl(
        turn_log_path(),
        {
            "kind": "turn_stop",
            "session_id": session_id,
            "reason": reason,
            "location": location,
            "metrics": metrics,
        },
    )
    agent_debug_log(
        "H2",
        location or "turn:stop",
        reason,
        {"session_id": session_id, **metrics},
    )


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

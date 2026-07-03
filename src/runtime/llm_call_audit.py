"""Persist every LiteLLM / vLLM request+response for turn debugging."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from haystack.dataclasses import ChatMessage

from src.haystack_chat import chat_message_text
from src.runtime.prompt_snapshot import _message_role, _serialize_message_content, serialize_tools

logger = logging.getLogger("aion.llm_call_audit")

_REPO_ROOT = Path(__file__).resolve().parents[2]


def llm_call_audit_enabled() -> bool:
    return os.getenv("AION_LLM_CALL_AUDIT", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def audit_root_dir() -> Path:
    explicit = (os.getenv("AION_LLM_CALL_AUDIT_DIR") or "").strip()
    if explicit:
        return Path(explicit)
    return _REPO_ROOT / "data" / "diagnostics" / "llm_calls"


def _index_path() -> Path:
    return audit_root_dir() / "index.jsonl"


def _redact_generation_kwargs(kwargs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not kwargs:
        return {}
    try:
        raw = json.loads(json.dumps(kwargs, default=str))
    except (TypeError, ValueError):
        return {"_error": "could not serialize generation_kwargs"}
    if isinstance(raw.get("api_key"), str):
        raw["api_key"] = "***"
    extra = raw.get("extra_body")
    if isinstance(extra, dict):
        for key in list(extra):
            if "key" in key.lower() or "secret" in key.lower() or "token" in key.lower():
                extra[key] = "***"
    return raw


def _serialize_tool_calls(message: ChatMessage) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for tc in getattr(message, "tool_calls", None) or []:
        entry: Dict[str, Any] = {
            "id": getattr(tc, "id", None),
            "tool_name": getattr(tc, "tool_name", None) or getattr(tc, "name", None),
        }
        args = getattr(tc, "arguments", None)
        if args is not None:
            if isinstance(args, dict):
                entry["arguments"] = args
            else:
                entry["arguments"] = str(args)
        out.append(entry)
    return out


def serialize_messages(messages: List[ChatMessage]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, message in enumerate(messages):
        content = _serialize_message_content(message)
        meta = getattr(message, "meta", None) or {}
        row: Dict[str, Any] = {
            "index": index,
            "role": _message_role(message),
            "content": content,
            "chars": len(content),
            "tool_calls": _serialize_tool_calls(message),
        }
        if isinstance(meta, dict):
            for key in ("reasoning", "reasoning_content"):
                if meta.get(key):
                    row[key] = str(meta[key])[:32_000]
            if meta.get("usage"):
                row["usage"] = meta["usage"]
        rows.append(row)
    return rows


def _serialize_tools_arg(tools: Optional[List[Any]]) -> List[Dict[str, Any]]:
    if not tools:
        return []

    class _ToolAgent:
        def __init__(self, tool_list: List[Any]):
            self.tools = tool_list

    return serialize_tools(_ToolAgent(tools))


def _turn_context() -> Dict[str, Any]:
    try:
        from src.runtime.context import get_context
        from src.runtime.turn_compaction import _turn_runtime

        ctx = get_context()
        rt = _turn_runtime.get() if _turn_runtime is not None else None
        out: Dict[str, Any] = {
            "session_id": (ctx or {}).get("session_id") or "",
            "turn_plan_id": (ctx or {}).get("turn_plan_id"),
        }
        if isinstance(rt, dict):
            out["profile_name"] = rt.get("profile_name")
            out["user_id"] = rt.get("user_id")
            agent = rt.get("agent")
            if agent is not None:
                sp = getattr(agent, "system_prompt", None)
                if sp:
                    out["system_prompt_chars"] = len(str(sp))
        return out
    except Exception:
        return {}


def _system_prompt_from_turn() -> str:
    try:
        from src.runtime.turn_compaction import _turn_runtime

        if _turn_runtime is None:
            return ""
        rt = _turn_runtime.get()
        if not isinstance(rt, dict):
            return ""
        agent = rt.get("agent")
        if agent is None:
            return ""
        sp = getattr(agent, "system_prompt", None) or ""
        return str(sp)
    except Exception:
        return ""


def _next_step(session_id: str) -> int:
    from src.runtime.turn_compaction import bump_llm_step

    step = bump_llm_step()
    if step > 0:
        return step
    # Fallback when turn runtime is missing (unit tests).
    idx = _index_path()
    if not idx.is_file() or not session_id:
        return 1
    count = 0
    try:
        with idx.open(encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("session_id") == session_id:
                    count += 1
    except OSError:
        pass
    return count + 1


def _write_call_file(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _append_index(row: Dict[str, Any]) -> None:
    idx = _index_path()
    idx.parent.mkdir(parents=True, exist_ok=True)
    with idx.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def record_llm_call(
    generator: Any,
    *,
    messages: List[ChatMessage],
    tools: Optional[List[Any]] = None,
    generation_kwargs: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> Optional[str]:
    """Write one JSON file per LLM call. Returns path string or None if disabled."""
    if not llm_call_audit_enabled():
        return None

    ctx = _turn_context()
    session_id = (ctx.get("session_id") or "unknown").strip() or "unknown"
    step = _next_step(session_id)
    call_id = uuid.uuid4().hex[:12]
    ts_ms = int(time.time() * 1000)

    system_prompt = _system_prompt_from_turn()
    request_block: Dict[str, Any] = {
        "model": getattr(generator, "model", None),
        "provider": getattr(generator, "provider", None),
        "api_base_url": getattr(generator, "api_base_url", None),
        "message_count": len(messages),
        "messages": serialize_messages(messages),
        "tools": _serialize_tools_arg(tools),
        "generation_kwargs": _redact_generation_kwargs(
            generation_kwargs or getattr(generator, "generation_kwargs", None) or {}
        ),
    }
    if system_prompt:
        request_block["system_prompt"] = system_prompt

    replies: List[Dict[str, Any]] = []
    if isinstance(result, dict):
        for msg in result.get("replies") or []:
            if isinstance(msg, ChatMessage):
                replies.append(
                    {
                        "role": _message_role(msg),
                        "content": _serialize_message_content(msg),
                        "tool_calls": _serialize_tool_calls(msg),
                        "meta": getattr(msg, "meta", None) or {},
                    }
                )

    payload: Dict[str, Any] = {
        "call_id": call_id,
        "step": step,
        "ts_ms": ts_ms,
        "session_id": session_id,
        "profile_name": ctx.get("profile_name"),
        "user_id": ctx.get("user_id"),
        "turn_plan_id": ctx.get("turn_plan_id"),
        "duration_ms": duration_ms,
        "request": request_block,
        "response": {
            "replies": replies,
            "error": error,
        },
    }

    rel = Path(session_id) / f"step_{step:04d}_{call_id}.json"
    path = audit_root_dir() / rel
    try:
        _write_call_file(path, payload)
        _append_index(
            {
                "ts_ms": ts_ms,
                "call_id": call_id,
                "step": step,
                "session_id": session_id,
                "profile_name": ctx.get("profile_name"),
                "path": str(rel),
                "message_count": len(messages),
                "tool_count": len(tools or []),
                "reply_count": len(replies),
                "tool_call_names": [
                    tc.get("tool_name")
                    for r in replies
                    for tc in (r.get("tool_calls") or [])
                    if tc.get("tool_name")
                ],
                "error": error,
                "duration_ms": duration_ms,
            }
        )
        return str(path)
    except Exception as exc:
        logger.warning("llm_call_audit write failed: %s", exc)
        return None

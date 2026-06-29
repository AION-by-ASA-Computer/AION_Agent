"""Serialize the full prompt sent to the Haystack agent (system + tools + messages)."""
from __future__ import annotations

import json
import os
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from haystack.dataclasses import ChatMessage

from src.haystack_chat import chat_message_text
from src.memory.context_compressor import estimate_full_prompt_tokens

_MAX_SNAPSHOTS_PER_SESSION = 20


def prompt_debug_enabled() -> bool:
    return os.getenv("AION_PROMPT_DEBUG", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _message_role(message: ChatMessage) -> str:
    role = getattr(message, "role", None)
    return str(role.value if hasattr(role, "value") else role or "user").lower()


def _extract_prefix(before: str, after: str) -> Optional[str]:
    """Return the prefix prepended to ``before`` to obtain ``after``, if any."""
    if not after or after == before:
        return None
    if after.endswith(before):
        prefix = after[: len(after) - len(before)]
        return prefix if prefix else None
    if after.startswith(before):
        suffix = after[len(before) :]
        return suffix if suffix else None
    return None


def track_prepend_layer(
    layers: List[Dict[str, str]],
    key: str,
    before: str,
    after: str,
) -> None:
    prefix = _extract_prefix(before, after)
    if prefix:
        layers.append({"key": key, "text": prefix})


def _serialize_message_content(message: ChatMessage) -> str:
    parts = getattr(message, "content_parts", None) or getattr(message, "parts", None)
    if parts:
        lines: List[str] = []
        for part in parts:
            if isinstance(part, str):
                lines.append(part)
                continue
            cls_name = type(part).__name__
            if cls_name == "ImageContent":
                meta = getattr(part, "meta", None) or {}
                rel = meta.get("relative_path") if isinstance(meta, dict) else None
                mime = getattr(part, "mime_type", None) or "image"
                lines.append(f"[IMAGE {mime}: {rel or 'embedded'}]")
                continue
            if cls_name == "FileContent":
                fname = getattr(part, "filename", None) or getattr(part, "name", None) or "file"
                lines.append(f"[FILE: {fname}]")
                continue
            text = chat_message_text(message)
            if text:
                lines.append(text)
            else:
                lines.append(f"[{cls_name}]")
        if lines:
            return "\n".join(lines)
    return chat_message_text(message)


def serialize_tools(agent: object) -> List[Dict[str, Any]]:
    tools = getattr(agent, "tools", None) or []
    out: List[Dict[str, Any]] = []
    for tool in tools:
        entry: Dict[str, Any] = {
            "name": getattr(tool, "name", "") or "",
            "description": getattr(tool, "description", "") or "",
        }
        spec = getattr(tool, "tool_spec", None)
        if spec is not None:
            try:
                entry["spec"] = (
                    spec
                    if isinstance(spec, dict)
                    else json.loads(json.dumps(spec, default=str))
                )
            except (TypeError, ValueError):
                entry["spec"] = str(spec)[:16_000]
        out.append(entry)
    return out


def build_prompt_snapshot(
    agent: object,
    messages: List[ChatMessage],
    *,
    inject_layers: Optional[List[Dict[str, str]]] = None,
    turn_meta: Optional[Dict[str, Any]] = None,
    generation_kwargs: Optional[Dict[str, Any]] = None,
    phase: str = "pre_run",
) -> Dict[str, Any]:
    system_prompt = getattr(agent, "system_prompt", None) or ""
    if not isinstance(system_prompt, str):
        system_prompt = str(system_prompt)

    serialized_messages: List[Dict[str, Any]] = []
    for index, message in enumerate(messages):
        content = _serialize_message_content(message)
        serialized_messages.append(
            {
                "index": index,
                "role": _message_role(message),
                "content": content,
                "chars": len(content),
            }
        )

    stats = estimate_full_prompt_tokens(agent, messages)
    raw_parts = ["=== SYSTEM ===", system_prompt, ""]
    for row in serialized_messages:
        raw_parts.append(f"=== {row['role'].upper()} [{row['index']}] ===")
        raw_parts.append(row["content"])
        raw_parts.append("")
    raw_concatenated = "\n".join(raw_parts)

    return {
        "phase": phase,
        "system_prompt": system_prompt,
        "tools": serialize_tools(agent),
        "messages": serialized_messages,
        "inject_layers": inject_layers or [],
        "stats": stats,
        "generation_kwargs": generation_kwargs or {},
        "turn_meta": turn_meta or {},
        "raw_concatenated": raw_concatenated,
    }


_SESSION_SNAPSHOTS: Dict[str, Deque[Dict[str, Any]]] = {}


def store_prompt_snapshot(
    session_id: str,
    snapshot: Dict[str, Any],
    *,
    assistant_message_id: Optional[str] = None,
) -> None:
    if not session_id:
        return
    row = {
        **snapshot,
        "assistant_message_id": assistant_message_id,
        "stored_at_ms": int(time.time() * 1000),
    }
    bucket = _SESSION_SNAPSHOTS.setdefault(session_id, deque(maxlen=_MAX_SNAPSHOTS_PER_SESSION))
    bucket.append(row)


def list_prompt_snapshots(session_id: str) -> List[Dict[str, Any]]:
    bucket = _SESSION_SNAPSHOTS.get(session_id)
    if not bucket:
        return []
    return list(bucket)


def clear_prompt_snapshots(session_id: Optional[str] = None) -> None:
    if session_id:
        _SESSION_SNAPSHOTS.pop(session_id, None)
        return
    _SESSION_SNAPSHOTS.clear()


def patch_prompt_snapshot_output(
    session_id: str,
    assistant_message_id: Optional[str],
    *,
    assistant_output: str,
    plan_coerced_markdown: Optional[str] = None,
    plan_intercepts: int = 0,
    plan_finalize_source: Optional[str] = None,
    plan_text_fallback_count: int = 0,
    artifact_parse_hits: int = 0,
    artifact_salvage: int = 0,
    raw_token_fallback_chunks: int = 0,
) -> Optional[Dict[str, Any]]:
    """Attach model output to the pre-run snapshot for Prompt debug (post-turn)."""
    if not session_id or not assistant_message_id:
        return None
    bucket = _SESSION_SNAPSHOTS.get(session_id)
    if not bucket:
        return None
    for row in reversed(bucket):
        if row.get("assistant_message_id") != assistant_message_id:
            continue
        row["phase"] = "complete"
        row["assistant_output"] = assistant_output or ""
        row["plan_coerced_markdown"] = plan_coerced_markdown
        row["plan_intercepts"] = int(plan_intercepts or 0)
        row["plan_finalize_source"] = plan_finalize_source
        row["plan_text_fallback_count"] = int(plan_text_fallback_count or 0)
        row["turn_metrics"] = {
            "artifact_parse_hits": int(artifact_parse_hits or 0),
            "artifact_salvage": int(artifact_salvage or 0),
            "raw_token_fallback_chunks": int(raw_token_fallback_chunks or 0),
            "plan_finalize_source": plan_finalize_source,
            "plan_text_fallback_count": int(plan_text_fallback_count or 0),
        }
        extra = ["", "=== ASSISTANT OUTPUT ===", assistant_output or ""]
        if plan_coerced_markdown:
            extra.extend(["", "=== PLAN COERCED ===", plan_coerced_markdown])
        metrics = row["turn_metrics"]
        extra.extend(
            [
                "",
                "=== TURN METRICS ===",
                f"artifact_parse_hits: {metrics['artifact_parse_hits']}",
                f"artifact_salvage: {metrics['artifact_salvage']}",
                f"raw_token_fallback_chunks: {metrics['raw_token_fallback_chunks']}",
                f"plan_finalize_source: {metrics.get('plan_finalize_source') or 'n/a'}",
                f"plan_text_fallback_count: {metrics.get('plan_text_fallback_count', 0)}",
            ]
        )
        row["raw_concatenated"] = (row.get("raw_concatenated") or "") + "\n".join(extra)
        return dict(row)
    return None

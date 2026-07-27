"""Pi custom compaction: summarize transcript with tool-aware details."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from src.memory.context_compressor import compaction_summary_prompt
from src.memory.llm_extract import complete_text_sync
from src.runtime.tool_ledger import (
    ledger_summary_lines,
    offload_paths_for_session,
    render_ledger_table,
)

logger = logging.getLogger("aion.pi_compaction")


def pi_custom_compaction_enabled() -> bool:
    return (os.getenv("AION_PI_CUSTOM_COMPACTION") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def pi_compaction_http_timeout() -> float:
    try:
        return max(10.0, float(os.getenv("AION_PI_COMPACTION_HTTP_TIMEOUT", "120")))
    except ValueError:
        return 120.0


def _merge_details(
    previous: Optional[Dict[str, Any]],
    file_ops: Optional[Dict[str, Any]],
    session_id: str,
) -> Dict[str, Any]:
    prev = dict(previous or {})
    ops = dict(file_ops or {})
    read_files = list(prev.get("readFiles") or ops.get("readFiles") or [])
    modified_files = list(prev.get("modifiedFiles") or ops.get("modifiedFiles") or [])
    tool_ledger = list(prev.get("toolLedger") or [])
    tool_ledger.extend(ledger_summary_lines(session_id))
    # dedupe while preserving order
    seen: set[str] = set()
    unique_ledger: List[str] = []
    for line in tool_ledger:
        if line in seen:
            continue
        seen.add(line)
        unique_ledger.append(line)
    offload_paths = list(prev.get("offloadPaths") or [])
    for p in offload_paths_for_session(session_id):
        if p not in offload_paths:
            offload_paths.append(p)
    return {
        "readFiles": read_files,
        "modifiedFiles": modified_files,
        "toolLedger": unique_ledger[-80:],
        "offloadPaths": offload_paths[-80:],
    }


def _append_tool_blocks(summary: str, details: Dict[str, Any]) -> str:
    lines = [summary.rstrip()]
    ledger = details.get("toolLedger") or []
    if ledger:
        lines.append("\n<tool-trace>")
        lines.extend(str(x) for x in ledger)
        lines.append("</tool-trace>")
    paths = details.get("offloadPaths") or []
    if paths:
        lines.append("\n<offloaded-results>")
        for p in paths:
            lines.append(str(p))
        lines.append("</offloaded-results>")
    read_files = details.get("readFiles") or []
    if read_files:
        lines.append("\n<read-files>")
        lines.extend(str(x) for x in read_files)
        lines.append("</read-files>")
    modified = details.get("modifiedFiles") or []
    if modified:
        lines.append("\n<modified-files>")
        lines.extend(str(x) for x in modified)
        lines.append("</modified-files>")
    return "\n".join(lines)


def summarize_for_pi_compaction(
    *,
    session_id: str,
    transcript: str,
    previous_summary: str = "",
    file_ops: Optional[Dict[str, Any]] = None,
    custom_instructions: str = "",
    previous_details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate compaction summary + cumulative details for Pi worker."""
    prompt = compaction_summary_prompt()
    if custom_instructions.strip():
        prompt += f"\n\nFocus: {custom_instructions.strip()}"
    user_parts: List[str] = []
    if previous_summary.strip():
        user_parts.append(f"Previous summary:\n{previous_summary.strip()}")
    user_parts.append(f"Conversation to summarize:\n{transcript[:120000]}")
    user_content = "\n\n".join(user_parts)

    summary = complete_text_sync(
        prompt,
        user_content,
        max_tokens=int(os.getenv("AION_CONTEXT_COMPRESS_SUMMARY_MAX_TOKENS", "4096")),
        timeout=pi_compaction_http_timeout(),
    )
    details = _merge_details(previous_details, file_ops, session_id)
    full_summary = _append_tool_blocks(summary or "", details)
    return {
        "summary": full_summary,
        "details": details,
    }


def render_ledger_for_pi(session_id: str) -> str:
    return render_ledger_table(session_id)

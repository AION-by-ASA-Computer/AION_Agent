"""Format wake/recall rows for agent consumption."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


def format_note_line(
    *,
    seq: int,
    content: str,
    created_at: Optional[datetime] = None,
    category: Optional[str] = None,
    scope_label: Optional[str] = None,
    confidence: Optional[float] = None,
) -> str:
    date_s = created_at.strftime("%Y-%m-%d") if created_at else ""
    prefix = f"[#{seq}]"
    if date_s:
        prefix += f" ({date_s})"
    if scope_label:
        prefix += f" ({scope_label})"
    if category:
        prefix += f" {category}:"
    body = content.strip()
    if confidence is not None and confidence < 0.75:
        body = f"~{body}~"
    return f"{prefix} {body}"


def format_digest_line(
    *,
    range_start: int,
    range_end: int,
    summary: str,
    scope_label: Optional[str] = None,
) -> str:
    label = f"[#{range_start}-{range_end - 1}]"
    if scope_label:
        label += f" ({scope_label})"
    return f"{label} (digest) {summary.strip()}"


def format_wake_block(
    rows: List[Dict[str, Any]], header: Optional[str] = None
) -> str:
    lines = [r.get("line", "") for r in rows if r.get("line")]
    if not lines:
        return ""
    body = "\n".join(lines)
    if header:
        return f"{header}\n{body}"
    return body

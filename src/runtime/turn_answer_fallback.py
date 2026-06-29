"""Fallback visible answer when the model ran tools but emitted no assistant text."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

_SQL_TOOL_NAME_RE = re.compile(
    r"(execute_sql|run_sql|sql_query|query_sql|mysql_query|postgres_query|\bsql\b)",
    re.I,
)


def _is_sql_tool(name: str) -> bool:
    return bool(_SQL_TOOL_NAME_RE.search(name or ""))


def _format_sql_output_preview(output: str, *, max_chars: int = 3500) -> str:
    text = (output or "").strip()
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    rows: List[Dict[str, Any]] = []
    for ln in lines[:40]:
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    if not rows:
        return text[:max_chars]
    if len(rows) == 1 and len(rows[0]) == 1:
        k, v = next(iter(rows[0].items()))
        return f"**{k}**: {v}"
    keys = list(rows[0].keys())[:6]
    header = " | ".join(keys)
    body_lines = []
    for row in rows[:12]:
        body_lines.append(" | ".join(str(row.get(k, ""))[:80] for k in keys))
    table = header + "\n" + "\n".join(body_lines)
    if len(rows) > 12:
        table += f"\n… ({len(rows)} righe totali)"
    return table[:max_chars]


def build_tool_result_fallback(
    pending_db_steps: List[Dict[str, Any]],
    *,
    max_chars: int = 3500,
) -> str:
    """Build a short user-visible summary from the last successful SQL tool output."""
    last_sql: Optional[Dict[str, Any]] = None
    for step in reversed(pending_db_steps or []):
        if step.get("is_error"):
            continue
        name = str(step.get("name") or "")
        out = str(step.get("output") or "").strip()
        if not out or not _is_sql_tool(name):
            continue
        last_sql = step
        break
    if not last_sql:
        return ""

    preview = _format_sql_output_preview(
        str(last_sql.get("output") or ""), max_chars=max_chars
    )
    if not preview:
        return ""

    intro = (
        "Tools ran but no final assistant message was emitted. "
        "Summary from the last SQL result:"
    )
    footer = "_Server-generated fallback — verify if needed._"
    return f"{intro}\n\n{preview}\n\n{footer}"

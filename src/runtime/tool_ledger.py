"""Persistent per-session tool call ledger (append-only JSONL)."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.session_workspace import safe_resolve

logger = logging.getLogger("aion.tool_ledger")

TOOL_RESULTS_REL = "derived/tool_results"
LEDGER_FILENAME = "_ledger.jsonl"

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._\-]+")


def tool_ledger_enabled() -> bool:
    raw = os.getenv("AION_TOOL_LEDGER_ENABLED")
    if raw is not None and str(raw).strip() != "":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    from src.settings import get_settings

    return bool(get_settings().tool_ledger_enabled)


def ledger_max_rows() -> int:
    raw = os.getenv("AION_TOOL_LEDGER_MAX_ROWS")
    if raw is not None and str(raw).strip() != "":
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    from src.settings import get_settings

    try:
        return max(1, int(get_settings().tool_ledger_max_rows))
    except (TypeError, ValueError):
        return 60


def ledger_max_chars() -> int:
    raw = os.getenv("AION_TOOL_LEDGER_MAX_CHARS")
    if raw is not None and str(raw).strip() != "":
        try:
            return max(500, int(raw))
        except ValueError:
            pass
    from src.settings import get_settings

    try:
        return max(500, int(get_settings().tool_ledger_max_chars))
    except (TypeError, ValueError):
        return 3000


def ledger_path(session_id: str) -> Path:
    rel = f"{TOOL_RESULTS_REL}/{LEDGER_FILENAME}"
    return safe_resolve(session_id, rel)


def _read_entries(session_id: str) -> List[Dict[str, Any]]:
    path = ledger_path(session_id)
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except json.JSONDecodeError:
                continue
    except OSError as exc:
        logger.debug("ledger read failed session=%s: %s", session_id[:8], exc)
    return rows


def next_ledger_seq(session_id: str) -> int:
    entries = _read_entries(session_id)
    if not entries:
        return 1
    return max(int(e.get("seq") or 0) for e in entries) + 1


def extract_target_hint(
    tool_name: str, arguments: Optional[Dict[str, Any]] = None
) -> str:
    """Short label for ledger (never full argument blobs)."""
    args = arguments or {}
    keys = ("url", "relative_path", "path", "query", "pattern", "command", "skill")
    for key in keys:
        val = args.get(key)
        if val is not None and str(val).strip():
            text = str(val).strip().replace("\n", " ")
            if len(text) > 60:
                return text[:57] + "..."
            return text
    if args:
        first = next(iter(args.values()), "")
        text = str(first).strip().replace("\n", " ")
        if text:
            return text[:60] if len(text) <= 60 else text[:57] + "..."
    return (tool_name or "tool")[:60]


@dataclass
class LedgerEntry:
    seq: int
    ts: float
    tool: str
    target: str
    ok: bool
    chars: int
    path: Optional[str] = None
    dur_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def append_ledger_entry(session_id: str, entry: LedgerEntry) -> None:
    if not tool_ledger_enabled():
        return
    sid = (session_id or "").strip()
    if not sid:
        return
    try:
        store_dir = safe_resolve(sid, TOOL_RESULTS_REL)
        store_dir.mkdir(parents=True, exist_ok=True)
        path = ledger_path(sid)
        line = json.dumps(entry.to_dict(), ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception as exc:
        logger.debug("ledger append failed session=%s: %s", sid[:8], exc)


def _format_chars(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def list_ledger_entries(session_id: str) -> List[Dict[str, Any]]:
    """Return parsed ledger rows for UI (empty when no ledger file)."""
    return _read_entries(session_id)


def render_ledger_table(
    session_id: str,
    *,
    max_rows: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> str:
    if not tool_ledger_enabled():
        return ""
    rows_limit = max_rows if max_rows is not None else ledger_max_rows()
    char_limit = max_chars if max_chars is not None else ledger_max_chars()
    entries = _read_entries(session_id)
    if not entries:
        return ""
    omitted = 0
    if len(entries) > rows_limit:
        omitted = len(entries) - rows_limit
        entries = entries[-rows_limit:]

    lines = [
        "--- Tool trace (this session) ---",
        "| # | tool | target | ok | chars | full result |",
        "|---|------|--------|----|-------|-------------|",
    ]
    for row in entries:
        seq = row.get("seq", "?")
        tool = str(row.get("tool") or "")[:24]
        target = str(row.get("target") or "")[:40]
        ok = "y" if row.get("ok", True) else "n"
        chars = _format_chars(int(row.get("chars") or 0))
        path = str(row.get("path") or "inline")
        lines.append(f"| {seq} | {tool} | {target} | {ok} | {chars} | {path} |")
    if omitted:
        lines.append(
            f"… {omitted} earlier calls omitted "
            f"(grep {TOOL_RESULTS_REL}/{LEDGER_FILENAME})"
        )
    lines.append("--- End tool trace ---")
    block = "\n".join(lines)
    if len(block) > char_limit:
        block = block[: char_limit - 20] + "\n… [ledger truncated]"
    return block


def ledger_summary_lines(session_id: str, *, max_lines: int = 40) -> List[str]:
    """Compact lines for compaction summaries."""
    entries = _read_entries(session_id)
    if not entries:
        return []
    out: List[str] = []
    for row in entries[-max_lines:]:
        seq = row.get("seq", "?")
        tool = row.get("tool", "")
        target = row.get("target", "")
        path = row.get("path") or "inline"
        chars = row.get("chars", 0)
        out.append(f"{seq}  {tool}  {target}  ok  {_format_chars(int(chars))}  {path}")
    return out


def offload_paths_for_session(session_id: str) -> List[str]:
    """Session-relative paths of offloaded tool result files."""
    try:
        store = safe_resolve(session_id, TOOL_RESULTS_REL, must_exist=True)
    except (FileNotFoundError, ValueError):
        return []
    if not store.is_dir():
        return []
    paths: List[str] = []
    for p in sorted(store.iterdir()):
        if not p.is_file() or p.name.startswith("_") or p.name == LEDGER_FILENAME:
            continue
        paths.append(f"{TOOL_RESULTS_REL}/{p.name}")
    return paths

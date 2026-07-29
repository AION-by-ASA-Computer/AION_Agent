"""Offload large tool results to session disk; return pointer + preview for LLM context."""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Set

from src.runtime.tool_ledger import (
    LedgerEntry,
    TOOL_RESULTS_REL,
    append_ledger_entry,
    extract_target_hint,
    ledger_path,
    next_ledger_seq,
    tool_ledger_enabled,
)
from src.session_workspace import safe_resolve

logger = logging.getLogger("aion.tool_offload")

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._\-]+")
_SCORE_RE = re.compile(r"\d+[–-]\d+")
# Wikipedia group/knockout pages: match narratives sit after intro + standings tables.
_WEB_FETCH_PREVIEW_MARKERS = (
    "All times listed are local",
    "| Pld |",
    "In the round of 32",
    "Round of 32",
    "Quarter-finals",
    "Semi-finals",
    "The final",
    "Final",
)


def offload_enabled() -> bool:
    raw = os.getenv("AION_TOOL_OFFLOAD_ENABLED")
    if raw is not None and str(raw).strip() != "":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    from src.settings import get_settings

    return bool(get_settings().tool_offload_enabled)


def offload_min_chars() -> int:
    raw = os.getenv("AION_TOOL_OFFLOAD_MIN_CHARS")
    if raw is not None and str(raw).strip() != "":
        try:
            return max(100, int(raw))
        except ValueError:
            pass
    from src.settings import get_settings

    try:
        return max(100, int(get_settings().tool_offload_min_chars))
    except (TypeError, ValueError):
        return 8000


def offload_preview_chars() -> int:
    raw = os.getenv("AION_TOOL_OFFLOAD_PREVIEW_CHARS")
    if raw is not None and str(raw).strip() != "":
        try:
            return max(200, int(raw))
        except ValueError:
            pass
    from src.settings import get_settings

    try:
        return max(200, int(get_settings().tool_offload_preview_chars))
    except (TypeError, ValueError):
        return 1500


def offload_max_total_bytes() -> int:
    raw = os.getenv("AION_TOOL_OFFLOAD_MAX_TOTAL_MB")
    if raw is not None and str(raw).strip() != "":
        try:
            mb = float(raw)
            return max(0, int(mb * 1024 * 1024))
        except ValueError:
            pass
    from src.settings import get_settings

    try:
        mb = float(get_settings().tool_offload_max_total_mb)
        return max(0, int(mb * 1024 * 1024))
    except (TypeError, ValueError):
        return 64 * 1024 * 1024


def offload_excluded_tools() -> Set[str]:
    raw = os.getenv("AION_TOOL_OFFLOAD_EXCLUDE")
    if raw is None:
        from src.settings import get_settings

        raw = get_settings().tool_offload_exclude or "web_search"
    raw = (raw or "").strip()
    if not raw:
        return set()
    return {t.strip().lower() for t in raw.split(",") if t.strip()}


def sanitize_slug(value: str, *, max_len: int = 48) -> str:
    text = _SLUG_RE.sub("_", (value or "").strip())
    text = text.replace("..", "_").strip("_")[:max_len]
    return text or "x"


def _smart_offload_preview(text: str, tool_name: str, preview_len: int) -> str:
    """Pick a preview window that includes match/score content when possible."""
    if preview_len >= len(text):
        return text
    tname = (tool_name or "").strip().lower()
    if tname != "web_fetch_page":
        return text[:preview_len]
    for marker in _WEB_FETCH_PREVIEW_MARKERS:
        idx = text.find(marker)
        if idx < 0:
            continue
        start = max(0, idx - 80)
        chunk = text[start : start + preview_len]
        if _SCORE_RE.search(chunk) or len(chunk) >= min(preview_len // 2, 600):
            return chunk
    score = _SCORE_RE.search(text)
    if score:
        start = max(0, score.start() - 350)
        return text[start : start + preview_len]
    return text[:preview_len]


@dataclass(frozen=True)
class OffloadedResult:
    text: str
    path: Optional[str]
    total_chars: int
    preview_chars: int
    offloaded: bool
    seq: Optional[int] = None


def _ensure_store_dir(session_id: str) -> Path:
    store = safe_resolve(session_id, TOOL_RESULTS_REL)
    store.mkdir(parents=True, exist_ok=True)
    return store


def _prune_store_if_needed(session_id: str) -> None:
    cap_bytes = offload_max_total_bytes()
    try:
        store = safe_resolve(session_id, TOOL_RESULTS_REL, must_exist=True)
    except (FileNotFoundError, ValueError):
        return
    files = [p for p in store.iterdir() if p.is_file() and not p.name.startswith("_")]
    total = sum(p.stat().st_size for p in files)
    if total <= cap_bytes:
        return
    files.sort(key=lambda p: p.stat().st_mtime)
    for p in files:
        if total <= cap_bytes:
            break
        try:
            size = p.stat().st_size
            p.unlink()
            total -= size
            logger.info(
                "tool_offload pruned session=%s file=%s",
                session_id[:8],
                p.name,
            )
        except OSError:
            continue


def _build_pointer_text(
    *,
    tool_name: str,
    rel_path: str,
    total_chars: int,
    preview: str,
) -> str:
    preview_chars = len(preview)
    return (
        f"[AION offload] tool={tool_name} chars={total_chars} preview={preview_chars}\n"
        f"path={rel_path}\n"
        "Retrieve: sandbox_read_file_chunk(relative_path="
        f'"{rel_path}", offset_lines=0, max_lines=500)\n'
        'List: sandbox_list_files(subdir="tool_results")\n'
        "Search scores: sandbox_grep_content(pattern=r'\\d+[-–]\\d+', "
        f'relative_root="derived", glob_filter="tool_results/*.txt")\n'
        "Note: offloaded pages are few long lines — use offset_lines=0 or grep, "
        "not large line offsets.\n"
        f"--- preview (first {preview_chars} chars) ---\n"
        f"{preview}\n"
        "--- end preview ---"
    )


def _record_ledger(
    session_id: str,
    *,
    seq: int,
    tool_name: str,
    target: str,
    ok: bool,
    chars: int,
    path: Optional[str],
    dur_ms: Optional[int] = None,
) -> None:
    if not tool_ledger_enabled():
        return
    append_ledger_entry(
        session_id,
        LedgerEntry(
            seq=seq,
            ts=time.time(),
            tool=tool_name,
            target=target,
            ok=ok,
            chars=chars,
            path=path,
            dur_ms=dur_ms,
        ),
    )


def offload_tool_result(
    result: str,
    *,
    session_id: str,
    tool_name: str,
    call_id: Optional[str] = None,
    seq: Optional[int] = None,
    arguments: Optional[Dict[str, Any]] = None,
    is_error: bool = False,
    dur_ms: Optional[int] = None,
) -> OffloadedResult:
    """Write full payload to disk when large; always append ledger when enabled."""
    text = str(result or "")
    total = len(text)
    tname = (tool_name or "").strip() or "tool"
    sid = (session_id or "").strip()
    target = extract_target_hint(tname, arguments)

    use_seq = seq
    if use_seq is None and sid:
        try:
            use_seq = next_ledger_seq(sid)
        except Exception:
            use_seq = 1

    if not offload_enabled() or not sid:
        _record_ledger(
            sid,
            seq=use_seq or 1,
            tool_name=tname,
            target=target,
            ok=not is_error,
            chars=total,
            path=None,
            dur_ms=dur_ms,
        )
        return OffloadedResult(
            text=text,
            path=None,
            total_chars=total,
            preview_chars=total,
            offloaded=False,
            seq=use_seq,
        )

    if tname.lower() in offload_excluded_tools():
        _record_ledger(
            sid,
            seq=use_seq or 1,
            tool_name=tname,
            target=target,
            ok=not is_error,
            chars=total,
            path=None,
            dur_ms=dur_ms,
        )
        return OffloadedResult(
            text=text,
            path=None,
            total_chars=total,
            preview_chars=total,
            offloaded=False,
            seq=use_seq,
        )

    if total < offload_min_chars():
        _record_ledger(
            sid,
            seq=use_seq or 1,
            tool_name=tname,
            target=target,
            ok=not is_error,
            chars=total,
            path=None,
            dur_ms=dur_ms,
        )
        return OffloadedResult(
            text=text,
            path=None,
            total_chars=total,
            preview_chars=total,
            offloaded=False,
            seq=use_seq,
        )

    try:
        _ensure_store_dir(sid)
        _prune_store_if_needed(sid)
        slug_tool = sanitize_slug(tname)
        slug_call = sanitize_slug(call_id or "call")
        file_name = f"{use_seq:04d}_{slug_tool}_{slug_call}.txt"
        rel_path = f"{TOOL_RESULTS_REL}/{file_name}"
        full_path = safe_resolve(sid, rel_path)
        full_path.write_text(text, encoding="utf-8")
        preview_len = min(offload_preview_chars(), total)
        preview = _smart_offload_preview(text, tname, preview_len)
        pointer = _build_pointer_text(
            tool_name=tname,
            rel_path=rel_path,
            total_chars=total,
            preview=preview,
        )
        _record_ledger(
            sid,
            seq=use_seq or 1,
            tool_name=tname,
            target=target,
            ok=not is_error,
            chars=total,
            path=rel_path,
            dur_ms=dur_ms,
        )
        return OffloadedResult(
            text=pointer,
            path=rel_path,
            total_chars=total,
            preview_chars=preview_len,
            offloaded=True,
            seq=use_seq,
        )
    except Exception as exc:
        logger.debug(
            "tool_offload failed session=%s tool=%s: %s",
            sid[:8] if sid else "?",
            tname,
            exc,
        )
        _record_ledger(
            sid,
            seq=use_seq or 1,
            tool_name=tname,
            target=target,
            ok=not is_error,
            chars=total,
            path=None,
            dur_ms=dur_ms,
        )
        return OffloadedResult(
            text=text,
            path=None,
            total_chars=total,
            preview_chars=total,
            offloaded=False,
            seq=use_seq,
        )


def process_tool_result_for_context(
    result: str,
    *,
    session_id: str,
    tool_name: str,
    call_id: Optional[str] = None,
    arguments: Optional[Dict[str, Any]] = None,
    is_error: bool = False,
    dur_ms: Optional[int] = None,
) -> tuple[str, Optional[Dict[str, Any]]]:
    """
    Offload when enabled, else truncate. Returns (context_text, details_or_none).
    """
    from src.runtime.turn_compaction import truncate_tool_result

    off = offload_tool_result(
        result,
        session_id=session_id,
        tool_name=tool_name,
        call_id=call_id,
        arguments=arguments,
        is_error=is_error,
        dur_ms=dur_ms,
    )
    if off.offloaded:
        details = {
            "offload_path": off.path,
            "total_chars": off.total_chars,
            "preview_chars": off.preview_chars,
            "seq": off.seq,
        }
        return off.text, details
    truncated = truncate_tool_result(result, tool_name=tool_name)
    return truncated, None


def cleanup_session_offloads(session_id: str) -> int:
    """Remove offloaded tool-result directory and ledger for a session. Returns bytes freed."""
    import shutil

    sid = (session_id or "").strip()
    if not sid:
        return 0
    freed = 0
    try:
        base = safe_resolve(sid, TOOL_RESULTS_REL)
        if base.exists():
            for p in base.rglob("*"):
                if p.is_file():
                    try:
                        freed += p.stat().st_size
                    except OSError:
                        pass
            shutil.rmtree(base, ignore_errors=True)
        ledger = ledger_path(sid)
        if ledger.exists():
            try:
                freed += ledger.stat().st_size
            except OSError:
                pass
            ledger.unlink(missing_ok=True)
        if freed:
            logger.info(
                "tool_offload cleanup session=%s freed_bytes=%s",
                sid[:12],
                freed,
            )
    except Exception as exc:
        logger.warning("tool_offload cleanup failed session=%s: %s", sid[:12], exc)
    return freed

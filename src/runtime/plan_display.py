"""Strip <plan> blocks from visible chat timeline (mirrors chat-ui planDisplay.ts)."""
from __future__ import annotations

import re
from typing import Literal

PlanCapturePhase = Literal["none", "open_tag", "body"]

_PLAN_BLOCK_RE = re.compile(r"<plan\b[^>]*>[\s\S]*?</plan>", re.IGNORECASE)
_PLAN_OPEN_RE = re.compile(r"<plan\b", re.IGNORECASE)
_PLAN_PSEUDO_OPEN_RE = re.compile(r"(?:^|\n)\s*plan\s+title\s*=", re.IGNORECASE)
_PLAN_CLOSE_RE = re.compile(r"</plan>", re.IGNORECASE)
_PLAN_PARTIAL_MARKERS = (
    "<plan title=",
    "<plan title",
    "<plan titl",
    "<plan tit",
    "<plan ti",
    "<plan t",
    "<plan ",
    "<plan",
    "plan title=",
    "plan title",
    "plan titl",
    "plan tit",
    "plan ti",
    "plan t",
    "plan ",
    "plan",
)
_QUOTED_NEWLINE_RE = re.compile(r'^[\s\S]*?"\s*(?:\r?\n|$)')


def _find_plan_open_index(text: str) -> int:
    direct = _PLAN_OPEN_RE.search(text)
    pseudo = _PLAN_PSEUDO_OPEN_RE.search(text)
    idx_direct = direct.start() if direct else -1
    idx_pseudo = pseudo.start() if pseudo else -1
    if idx_direct < 0 and idx_pseudo < 0:
        return -1
    if idx_direct < 0:
        return idx_pseudo
    if idx_pseudo < 0:
        return idx_direct
    return min(idx_direct, idx_pseudo)


def _trailing_partial(text: str, markers: tuple[str, ...] = _PLAN_PARTIAL_MARKERS) -> int:
    best = 0
    for marker in markers:
        max_keep = len(marker) - 1
        for keep in range(max_keep, 0, -1):
            if text.endswith(marker[:keep]):
                best = max(best, keep)
                break
    return best


def _consume_plan_open_tag(rest: str) -> tuple[int, bool]:
    gt = rest.find(">")
    if gt >= 0:
        return gt + 1, True
    m = _QUOTED_NEWLINE_RE.match(rest)
    if m:
        return len(m.group(0)), True
    return 0, False


def strip_plan_blocks_for_chat_display(text: str) -> str:
    if not text:
        return ""
    out = _PLAN_BLOCK_RE.sub("", text)
    out = re.sub(r"(?:^|\n)\s*plan\s+title\s*=[\s\S]*$", "", out, flags=re.IGNORECASE)
    out = re.sub(r"<plan\b[\s\S]*$", "", out, flags=re.IGNORECASE)
    out = re.sub(r'(?:^|\n)\s*=\s*"[^"]*"[\s\S]*$', "", out, flags=re.IGNORECASE)
    return out.strip()


def feed_plan_aware_display(
    piece: str,
    phase: PlanCapturePhase = "none",
    pending: str = "",
) -> tuple[str, PlanCapturePhase, str]:
    """Return (visible_piece, phase_after, pending_buffer)."""
    if not piece and not pending:
        return "", phase, ""

    rest = (pending or "") + (piece or "")
    pending_out = ""
    out_parts: list[str] = []
    current: PlanCapturePhase = phase

    while rest:
        if current == "none":
            open_idx = _find_plan_open_index(rest)
            if open_idx < 0:
                partial = _trailing_partial(rest)
                if partial:
                    out_parts.append(rest[: len(rest) - partial])
                    pending_out = rest[-partial:]
                else:
                    out_parts.append(rest)
                break
            out_parts.append(rest[:open_idx])
            rest = rest[open_idx:]
            current = "open_tag"
            continue

        if current == "open_tag":
            consumed, complete = _consume_plan_open_tag(rest)
            if not complete:
                pending_out = rest
                break
            rest = rest[consumed:]
            current = "body"
            continue

        close_m = _PLAN_CLOSE_RE.search(rest)
        if close_m is None:
            partial = _trailing_partial(rest, ("</plan>", "</plan", "</pla", "</pl", "</p", "</", "<"))
            if partial:
                pending_out = rest[-partial:]
                rest = rest[: len(rest) - partial]
            break
        rest = rest[close_m.end() :]
        current = "none"

    return "".join(out_parts), current, pending_out

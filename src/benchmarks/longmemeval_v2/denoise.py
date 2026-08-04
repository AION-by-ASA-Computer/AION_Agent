"""Accessibility-tree denoising for LME-V2 ingest."""

from __future__ import annotations

import os
import re
from collections import Counter
from typing import Iterable, List, Set

_NODE_ID_RE = re.compile(r"^\s*\[\d+\]\s*")
_NOISE_ATTR_RE = re.compile(
    r",\s*(?:live='[^']*'|atomic|relevant='[^']*'|describedby='[^']*'"
    r"|owns='[^']*'|controls='[^']*'|focused|clickable|visible"
    r"|autocomplete='[^']*'|hasPopup='[^']*'|orientation='[^']*'"
    r"|multiselectable=\w+|pressed='[^']*'|expanded=\w+|selected=\w+)",
    re.IGNORECASE,
)
_EMPTY_CONTAINER_RE = re.compile(
    r"^(?:generic|region|navigation|group|list|listitem|LayoutTable|"
    r"LayoutTableRow|LayoutTableCell|paragraph|Section)\s*(?:''|)?\s*$",
    re.IGNORECASE,
)


def strip_node_line(raw: str) -> str:
    """Normalize one accessibility-tree line (strip ids and noise attrs)."""
    ln = (raw or "").strip()
    if not ln:
        return ""
    ln = _NODE_ID_RE.sub("", ln)
    prev = None
    while prev != ln:
        prev = ln
        ln = _NOISE_ATTR_RE.sub("", ln)
    return ln.strip().rstrip(",")


def denoise_tree(tree: str) -> List[str]:
    """Return cleaned non-empty lines from an accessibility tree."""
    if not (tree or "").strip():
        return []
    out: List[str] = []
    seen: set[str] = set()
    for raw in tree.splitlines():
        ln = strip_node_line(raw)
        if not ln or _EMPTY_CONTAINER_RE.match(ln):
            continue
        if ln in seen:
            continue
        seen.add(ln)
        out.append(ln)
    return out


def collect_boilerplate(
    state_line_lists: Iterable[List[str]],
    *,
    threshold: float | None = None,
) -> Set[str]:
    """Lines appearing in >= threshold fraction of states become chrome boilerplate."""
    if threshold is None:
        threshold = float(os.getenv("AION_LME_V2_BOILERPLATE_THRESHOLD", "0.6"))
    lists = list(state_line_lists)
    if not lists:
        return set()
    total = len(lists)
    freq: Counter[str] = Counter()
    for lines in lists:
        for line in set(lines):
            freq[line] += 1
    min_count = max(1, int(total * threshold))
    return {line for line, count in freq.items() if count >= min_count}


def filter_boilerplate(lines: List[str], boilerplate: Set[str]) -> List[str]:
    if not boilerplate:
        return list(lines)
    return [ln for ln in lines if ln not in boilerplate]


def boilerplate_note(boilerplate: Set[str], *, max_chars: int = 480) -> str:
    """Single chrome note for the whole run."""
    ordered = sorted(boilerplate)
    body = "ui_chrome: " + "; ".join(ordered)
    if len(body) <= max_chars:
        return body
    return body[: max_chars - 3] + "..."

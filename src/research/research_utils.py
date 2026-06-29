"""Shared utilities for the deep research system."""

from __future__ import annotations

import re

LOW_QUALITY_MARKERS = [
    "insufficient to",
    "content is insufficient",
    "no substantive data",
    "does not contain",
    "not relevant to",
    "no relevant information",
    "unable to extract",
    "completely unrelated",
    "boilerplate",
    "footer text",
    "cookie consent",
    "cookie banner",
    "cookie notice",
    "copyright notice",
    "copyright footer",
    "all rights reserved",
]

_THINK_PATTERNS = [
    re.compile(r"<thinking>[\s\S]*?</thinking>", re.I),
    re.compile(r"<think>[\s\S]*?</think>", re.I),
]


def strip_thinking(text):
    """Strip thinking/reasoning blocks from LLM output."""
    if text is None:
        return None
    out = str(text)
    for pat in _THINK_PATTERNS:
        out = pat.sub("", out)
    return out.strip()


def is_low_quality(summary: str) -> bool:
    """Check if a finding summary indicates useless or irrelevant content."""
    try:
        if not isinstance(summary, str) or not summary:
            return True
        low = summary.lower()
        return any(marker in low for marker in LOW_QUALITY_MARKERS)
    except Exception:
        return False

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
    "we need answer",
    "need process webpage",
    "need output json",
    "user goal in",
    "output json with",
    "task guidelines",
]

# Markers that indicate raw LLM reasoning/chain-of-thought has leaked into
# the report. These appear in the internal thinking stream of reasoning models
# (Qwen3, DeepSeek-R1, QwQ) when the visible content is empty and we
# accidentally use reasoning_content as a fallback.
REASONING_LEAKAGE_MARKERS = [
    "need maybe",
    "need include",
    "need provide",
    "need output",
    "need write",
    "need produce final report",
    "need answer user",
    "we need answer",
    "need ensure table",
    "need ensure markdown",
    "need note source",
    "need cite source",
    "need structure",
    "need cover all",
    "need check if",
    "need verify",
    "let me think",
    "let me consider",
    "i need to",
    "i should write",
    "i should include",
    "i will now write",
    "i will write the",
    "okay, let me",
    "alright, let me",
    "first, i need",
    "hmm, let me",
    "so the question is",
    "the user wants",
    "the user asked",
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
    res = out.strip()
    if res:
        return res
    # If stripping removed all content because the entire generation was inside <think>...</think>,
    # only preserve the inner content if it does NOT look like internal reasoning monologue.
    raw = str(text).strip()
    raw = re.sub(r"^<(?:think|thinking)>", "", raw, flags=re.I).strip()
    raw = re.sub(r"</(?:think|thinking)>$", "", raw, flags=re.I).strip()
    if is_reasoning_leakage(raw, threshold=1):
        return ""
    return raw


def is_low_quality(summary: str) -> bool:
    """Check if a finding summary explicitly indicates useless or irrelevant content."""
    try:
        if not isinstance(summary, str) or not summary.strip():
            return False
        low = summary.lower()
        return any(marker in low for marker in LOW_QUALITY_MARKERS)
    except Exception:
        return False


def is_reasoning_leakage(text: str, *, threshold: int = 3) -> bool:
    """Detect if text is raw LLM chain-of-thought that leaked into a report.

    Reasoning models (Qwen3, DeepSeek-R1, QwQ) produce internal thinking that
    should never appear in the final report. When the visible content is empty
    and reasoning_content is accidentally used as a fallback, this function
    detects the characteristic patterns of that internal monologue.

    Args:
        text: The text to check.
        threshold: Minimum number of distinct markers that must match (default 3).
                   Higher values reduce false positives for legitimate reports
                   that happen to use some of these phrases.

    Returns:
        True if the text appears to be raw reasoning output, not a final report.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    low = text.lower()
    hits = sum(1 for marker in REASONING_LEAKAGE_MARKERS if marker in low)
    return hits >= threshold

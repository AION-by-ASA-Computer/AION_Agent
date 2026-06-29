"""Resolve skill slug aliases (artifact_protocol variants)."""

from __future__ import annotations

import os
from typing import Optional


def artifact_strategy(strategy: Optional[str] = None) -> str:
    raw = (
        strategy
        if strategy is not None
        else os.getenv("AION_ARTIFACT_STRATEGY", "markdown")
    )
    return (raw or "markdown").strip().lower()


def resolve_skill_alias(skill_name: str, strategy: Optional[str] = None) -> str:
    """Map logical skill names to on-disk variants (single source of truth)."""
    if skill_name != "artifact_protocol":
        return skill_name
    strat = artifact_strategy(strategy)
    if strat == "markdown":
        return "artifact_protocol_markdown"
    if strat == "tool":
        return "artifact_protocol_tool"
    if strat == "xml":
        return "artifact_protocol_xml"
    return "artifact_protocol_markdown"

"""Resolve skill slug aliases."""

from __future__ import annotations

from typing import Optional


def resolve_skill_alias(skill_name: str, strategy: Optional[str] = None) -> str:
    """Map logical skill names to on-disk skill files."""
    del strategy  # legacy callers; artifact protocol is no longer strategy-specific
    if skill_name == "artifact_protocol":
        return "artifact_protocol"
    return skill_name

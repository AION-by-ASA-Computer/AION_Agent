"""Sandbox tools hidden or exposed per delivery policy."""

from __future__ import annotations

import os

# OpenCode-style: write tool is primary; no longer blocked for stream artifacts.
STREAM_ARTIFACT_BLOCKED_TOOLS: frozenset[str] = frozenset()

_LEGACY_STREAM_BLOCK = frozenset({"sandbox_write_workspace_file"})


def stream_artifact_tools_blocked(strategy: str | None = None) -> frozenset[str]:
    """Tool names removed from the agent tool list."""
    del strategy  # legacy parameter
    if os.getenv("AION_ARTIFACT_STREAM_LEGACY", "0").lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return _LEGACY_STREAM_BLOCK
    return STREAM_ARTIFACT_BLOCKED_TOOLS

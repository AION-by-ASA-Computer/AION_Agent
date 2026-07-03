"""Register Haystack tools for phantom tool names and the invalid sink."""

from __future__ import annotations

from haystack.tools import Tool

from src.tools import settlement_tools as st


def build_settlement_tools() -> list[Tool]:
    """Stub tools that return explicit errors when the model hallucinates file-creation tools."""
    return [
        Tool(
            name="invalid",
            description="Do not use. Internal settlement tool for invalid tool calls.",
            function=st.invalid_tool,
            parameters={
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "error": {"type": "string"},
                },
            },
        ),
        Tool(
            name="aion_artifact",
            description=(
                "NOT A TOOL — do not call. Create files with sandbox_write_workspace_file "
                "or sandbox_apply_patch instead."
            ),
            function=st.aion_artifact,
            parameters={"type": "object", "properties": {}},
        ),
        Tool(
            name="artifact",
            description="NOT A TOOL — use sandbox_write_workspace_file for new files.",
            function=st.artifact,
            parameters={"type": "object", "properties": {}},
        ),
        Tool(
            name="create_file",
            description="NOT A TOOL — use sandbox_write_workspace_file for new files.",
            function=st.create_file,
            parameters={"type": "object", "properties": {}},
        ),
    ]

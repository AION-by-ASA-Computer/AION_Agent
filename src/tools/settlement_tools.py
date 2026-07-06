"""Haystack-callable settlement stubs (top-level functions for Tool.to_dict)."""

from __future__ import annotations

from src.runtime.tool_settlement import phantom_tool_message


def invalid_tool(tool: str = "", error: str = "") -> str:
    """OpenCode-style invalid tool sink — model should not call this directly."""
    from src.runtime.tool_settlement import invalid_arguments_message
    import json

    detail = error or "invalid tool invocation"
    return json.dumps(
        {
            "ok": False,
            "error": "invalid_tool",
            "tool": tool or "invalid",
            "message": invalid_arguments_message(tool or "invalid", detail),
        },
        ensure_ascii=False,
    )


def aion_artifact(**_kwargs) -> str:
    return phantom_tool_message("aion_artifact")


def artifact(**_kwargs) -> str:
    return phantom_tool_message("artifact")


def create_file(**_kwargs) -> str:
    return phantom_tool_message("create_file")

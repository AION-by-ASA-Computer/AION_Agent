"""Tool execution protocol helpers (Pi-inspired)."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from src.runtime.harness_flags import harness_v2_tools


def tool_protocol_enabled() -> bool:
    return harness_v2_tools()


BeforeToolHook = Callable[[str, Dict[str, Any]], Optional[Dict[str, Any]]]


def format_tool_error(tool_name: str, exc: BaseException) -> str:
    from src.runtime.mcp_tool_result import format_exception_for_tool

    return format_exception_for_tool(tool_name, exc)


def should_skip_tools_for_truncation(finish_reason: Optional[str]) -> bool:
    return tool_protocol_enabled() and str(finish_reason or "") == "length"


def run_before_tool_call(
    tool_name: str,
    args: Dict[str, Any],
    hook: Optional[BeforeToolHook] = None,
) -> tuple[Dict[str, Any], Optional[str]]:
    """Returns (args, block_reason). block_reason set => return as tool error."""
    if not tool_protocol_enabled() or hook is None:
        return args, None
    try:
        result = hook(tool_name, dict(args))
    except Exception as exc:
        return args, format_tool_error(tool_name, exc)
    if isinstance(result, dict) and result.get("block"):
        return args, str(result.get("reason") or "Tool call blocked.")
    if isinstance(result, dict) and "args" in result:
        return dict(result["args"]), None
    return args, None

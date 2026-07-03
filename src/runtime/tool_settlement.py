"""
OpenCode-style tool settlement: phantom tools, unknown tools, invalid arguments.

See opencode packages/opencode/src/tool/invalid.ts and session/llm.ts repairToolCall.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, FrozenSet, Optional, Set

# Tools the model hallucinates when prompts mention <aion_artifact> — not real MCP tools.
PHANTOM_TOOL_NAMES: FrozenSet[str] = frozenset(
    {
        "aion_artifact",
        "artifact",
        "create_file",
        "create_artifact",
        "emit_artifact",
        "write_file",
        "write",
    }
)

# Registered but must not be called by the model (settlement-only).
INTERNAL_TOOL_NAMES: FrozenSet[str] = frozenset({"invalid"})

_JSON_RECOVERY_ALLOW_EMPTY = os.getenv("AION_JSON_RECOVERY_ALLOW_EMPTY", "0").lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def json_recovery_allow_empty() -> bool:
    return _JSON_RECOVERY_ALLOW_EMPTY


def tool_base_name(tool_name: str) -> str:
    return (tool_name or "").split("-")[-1].strip().lower()


def is_phantom_tool(tool_name: str) -> bool:
    base = tool_base_name(tool_name)
    return base in PHANTOM_TOOL_NAMES or (tool_name or "").strip().lower() in PHANTOM_TOOL_NAMES


def invalid_arguments_message(tool: str, detail: str) -> str:
    return (
        f"The {tool} tool was called with invalid arguments: {detail}. "
        "Please rewrite the input so it satisfies the expected schema."
    )


def phantom_tool_message(tool_name: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "error": "phantom_tool",
            "tool": tool_name,
            "message": (
                f"'{tool_name}' is NOT a registered tool. "
                "File creation uses sandbox_write_workspace_file or sandbox_apply_patch. "
                "Do NOT call aion_artifact, artifact, or create_file as tools."
            ),
            "hint": (
                "Use sandbox_write_workspace_file(relative_path, content) for new files, "
                "sandbox_edit_workspace_file for surgical edits, "
                "or sandbox_apply_patch(patch_text) on GPT-style models."
            ),
        },
        ensure_ascii=False,
    )


def unknown_tool_message(tool_name: str, registered_sample: Optional[Set[str]] = None) -> str:
    hint = ""
    if registered_sample:
        sample = sorted(registered_sample)[:12]
        hint = f" Registered tools include: {', '.join(sample)}."
    return json.dumps(
        {
            "ok": False,
            "error": "unknown_tool",
            "tool": tool_name,
            "message": f"Unknown tool '{tool_name}'.{hint}",
        },
        ensure_ascii=False,
    )


def settle_tool_call(
    tool_name: str,
    kwargs: Optional[Dict[str, Any]],
    *,
    registered_tools: Optional[Set[str]] = None,
) -> Optional[str]:
    """
    Return error JSON string if the call must not proceed, else None.

    Call before prepare_mcp_tool_arguments / MCP invoke.
    """
    name = (tool_name or "").strip()
    if not name:
        return unknown_tool_message(name or "(empty)", registered_tools)

    if is_phantom_tool(name):
        return phantom_tool_message(name)

    base = tool_base_name(name)
    if registered_tools is not None:
        known = {tool_base_name(t) for t in registered_tools} | {
            (t or "").strip().lower() for t in registered_tools
        }
        if base not in known and name.lower() not in known:
            return unknown_tool_message(name, registered_tools)

    if not _JSON_RECOVERY_ALLOW_EMPTY and kwargs is not None:
        from src.runtime.mcp_tool_args import tool_has_required_fields, missing_required_fields

        if tool_has_required_fields(name) and not kwargs:
            detail = f"missing required fields: {', '.join(missing_required_fields(name, kwargs))}"
            return json.dumps(
                {
                    "ok": False,
                    "error": "invalid_arguments",
                    "tool": name,
                    "message": invalid_arguments_message(name, detail),
                },
                ensure_ascii=False,
            )

    return None

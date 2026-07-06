"""
Model-specific tool exposure (OpenCode registry.ts pattern).

GPT models (non-gpt-4, non-oss): sandbox_apply_patch replaces write + edit.
Other models: write + edit, hide apply_patch.
"""

from __future__ import annotations

import os
from typing import FrozenSet, Iterable, List, Set

_APPLY_PATCH_TOOL = "sandbox_apply_patch"
_WRITE_TOOL = "sandbox_write_workspace_file"
_EDIT_TOOL = "sandbox_edit_workspace_file"

_GPT_PATCH_TOOLS: FrozenSet[str] = frozenset({_APPLY_PATCH_TOOL})
_DEFAULT_FILE_TOOLS: FrozenSet[str] = frozenset({_WRITE_TOOL, _EDIT_TOOL})


def model_tool_policy_enabled() -> bool:
    return os.getenv("AION_MODEL_TOOL_POLICY", "1").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def model_prefers_apply_patch(provider: str, model_id: str) -> bool:
    """OpenCode: gpt-* (not oss, not gpt-4) uses apply_patch instead of write/edit."""
    if not model_tool_policy_enabled():
        return False
    mid = (model_id or "").lower()
    prov = (provider or "").lower()
    if "oss" in mid:
        return False
    if "gpt-4" in mid:
        return False
    if mid.startswith("gpt-") or "codex" in mid:
        return True
    if prov in ("openai",) and "gpt" in mid:
        return True
    return False


def filter_tools_for_model(
    tools: Iterable,
    *,
    provider: str,
    model_id: str,
) -> List:
    """Return tools list with write/edit vs apply_patch gating applied."""
    tool_list = list(tools)
    if not model_tool_policy_enabled():
        return tool_list

    use_patch = model_prefers_apply_patch(provider, model_id)
    kept: List = []
    removed: Set[str] = set()

    for t in tool_list:
        name = getattr(t, "name", None) or ""
        base = name.split("-")[-1].strip().lower()
        if use_patch:
            if base in _DEFAULT_FILE_TOOLS or name in _DEFAULT_FILE_TOOLS:
                removed.add(name)
                continue
        else:
            if base in _GPT_PATCH_TOOLS or name in _GPT_PATCH_TOOLS:
                removed.add(name)
                continue
        kept.append(t)

    if removed:
        import logging

        logging.getLogger("aion.model_tool_policy").info(
            "model_tool_policy provider=%s model=%s use_patch=%s removed=%s",
            provider,
            model_id,
            use_patch,
            sorted(removed),
        )
    return kept


def hidden_tool_names_for_model(provider: str, model_id: str) -> FrozenSet[str]:
    if model_prefers_apply_patch(provider, model_id):
        return _DEFAULT_FILE_TOOLS
    return _GPT_PATCH_TOOLS

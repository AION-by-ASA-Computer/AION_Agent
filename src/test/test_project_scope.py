"""Project scope hints from DB metadata (no hardcoded slugs)."""
from __future__ import annotations

from src.memory.project_memory_scope import (
    project_context_block,
    project_scope_hint_from_meta,
)


def test_scope_from_description() -> None:
    hint = project_scope_hint_from_meta(
        "aion_am",
        display_name="Asset Manager",
        description="Navigazione DB Asset Manager, schema finance.",
    )
    assert "finance" in hint
    assert "aion_am" in hint


def test_scope_fallback_display_name() -> None:
    hint = project_scope_hint_from_meta("vendite", display_name="Vendite EU")
    assert "Vendite EU" in hint
    assert "vendite" in hint


def test_scope_generic_without_meta() -> None:
    hint = project_scope_hint_from_meta("custom_proj")
    assert "custom_proj" in hint
    assert "wing_proj_custom_proj" in project_context_block("custom_proj")

"""Tests for MemPalace wing scoping from SQL QueryMemory turn context."""

from __future__ import annotations

from src.memory.project_memory_scope import project_wing
from src.runtime.mempalace_tool_scope import (
    apply_mempalace_project_scope,
    is_legacy_navigation_wing,
)
from src.runtime.sql_query_memory_context import (
    clear_sql_qm_turn_context,
    set_sql_qm_turn_context,
)


def test_apply_scope_overrides_wing():
    set_sql_qm_turn_context(
        user_id="u1",
        profile_slug="postgres_metadata_assistant",
        project_slug="vendite",
        session_id="sess-1",
    )
    try:
        out = apply_mempalace_project_scope(
            "mempalace_add_drawer",
            {"wing": "alibr", "room": "join_paths", "content": "x"},
        )
        assert out["wing"] == project_wing("vendite")
        assert out["room"] == "join_paths"
    finally:
        clear_sql_qm_turn_context()


def test_apply_scope_no_context_unchanged():
    out = apply_mempalace_project_scope(
        "mempalace_search", {"wing": "alibr", "query": "ordini"}
    )
    assert out["wing"] == "alibr"


def test_apply_scope_overrides_other_project_wing():
    set_sql_qm_turn_context(
        user_id="u1",
        profile_slug="postgres_metadata_assistant",
        project_slug="am_2_new",
        session_id="sess-wing-2",
    )
    try:
        out = apply_mempalace_project_scope(
            "mempalace_add_drawer",
            {"wing": "wing_proj_aion_am", "room": "join_paths", "content": "x"},
        )
        assert out["wing"] == project_wing("am_2_new")
    finally:
        clear_sql_qm_turn_context("sess-wing-2")

"""Hard project binding for SQL QueryMemory tools."""

from __future__ import annotations

import pytest

from src.runtime.sql_query_memory_context import (
    clear_sql_qm_turn_context,
    set_sql_qm_turn_context,
)
from src.runtime.sql_query_project_scope import (
    apply_sql_query_project_scope,
    block_project_list_tool,
    bound_sql_project,
)


def test_bound_project_from_turn_context():
    set_sql_qm_turn_context(
        user_id="u1",
        profile_slug="mysql_metadata_assistant",
        project_slug="am_2_new",
        session_id="sess-scope-1",
    )
    try:
        assert bound_sql_project("sess-scope-1") == "am_2_new"
    finally:
        clear_sql_qm_turn_context("sess-scope-1")


def test_apply_scope_overrides_agent_project():
    set_sql_qm_turn_context(
        user_id="u1",
        profile_slug="mysql_metadata_assistant",
        project_slug="am_2_new",
        session_id="sess-scope-2",
    )
    try:
        out = apply_sql_query_project_scope(
            "sql_memory_save",
            {"project": "aion_am", "sql": "select 1", "request": "x"},
            session_id="sess-scope-2",
        )
        assert out["project"] == "am_2_new"
        assert "namespace" not in out
    finally:
        clear_sql_qm_turn_context("sess-scope-2")


def test_apply_scope_overrides_agent_project_on_delete():
    set_sql_qm_turn_context(
        user_id="u1",
        profile_slug="mysql_metadata_assistant",
        project_slug="am_2_new",
        session_id="sess-scope-del",
    )
    try:
        out = apply_sql_query_project_scope(
            "delete_sql_memory_entry",
            {"id": 22, "project": "aion_am"},
            session_id="sess-scope-del",
        )
        assert out["project"] == "am_2_new"
        assert out["id"] == 22
    finally:
        clear_sql_qm_turn_context("sess-scope-del")


def test_block_list_projects_when_bound():
    set_sql_qm_turn_context(
        user_id="u1",
        profile_slug="mysql_metadata_assistant",
        project_slug="am_2_new",
        session_id="sess-scope-3",
    )
    try:
        msg = block_project_list_tool("sql_memory_list_projects", "sess-scope-3")
        assert msg is not None
        assert "disabled" in msg.lower()
    finally:
        clear_sql_qm_turn_context("sess-scope-3")


@pytest.mark.anyio
async def test_verify_user_project_access_conditional_blocking():
    from src.runtime.sql_query_project_scope import verify_user_project_access

    # 1. Blocking when profile has memory capability (e.g. mysql_metadata_assistant)
    err = await verify_user_project_access(
        project_slug="default",
        profile_slug="mysql_metadata_assistant",
    )
    assert err is not None
    assert "default SQL QueryMemory project is disabled" in err

    # 2. No blocking when profile does not have memory capability (e.g. graphic_designer)
    err2 = await verify_user_project_access(
        project_slug="default",
        profile_slug="graphic_designer",
    )
    assert err2 is None

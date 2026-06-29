"""SQL QueryMemory exploration gate."""

from __future__ import annotations

import os
from unittest.mock import patch

from src.runtime.sql_query_memory_context import (
    clear_sql_qm_turn_context,
    mark_execute_sql_failed,
    mark_execute_sql_succeeded,
    set_sql_qm_turn_context,
)
from src.runtime.sql_query_memory_gate import (
    block_exploration_tool_if_sql_cache,
    extract_schemas_from_sql_text,
)


def test_extract_schemas_from_from_join_only() -> None:
    sql = """
    with ultime_mov as (
      select dm.device_id from aion_assetmanager_2.DeviceMovement dm
    )
    select u.device_id from ultime_mov u
    join aion_assetmanager_2.Device d on u.device_id = d.device_id
    """
    schemas = extract_schemas_from_sql_text(sql)
    assert "aion_assetmanager_2" in schemas
    assert "dm" not in schemas
    assert "u" not in schemas
    assert "d" not in schemas


def test_block_exploration_until_success() -> None:
    clear_sql_qm_turn_context()
    set_sql_qm_turn_context(
        user_id="u1",
        profile_slug="mysql_metadata_assistant",
        project_slug="aion_am",
        session_id="sess1",
        sql_cache_inject_active=True,
        sql_cache_schemas=("aion_assetmanager_2",),
    )
    with patch.dict(os.environ, {"AION_SQL_QM_GATE_EXPLORATION": "1"}, clear=False):
        assert (
            block_exploration_tool_if_sql_cache(
                "mempalace", "mempalace_search", "sess1"
            )
            is not None
        )
        mark_execute_sql_succeeded("sess1")
        assert (
            block_exploration_tool_if_sql_cache(
                "mempalace", "mempalace_search", "sess1"
            )
            is None
        )
    clear_sql_qm_turn_context("sess1")


def test_gate_unlocks_after_failed_execute_sql() -> None:
    clear_sql_qm_turn_context()
    set_sql_qm_turn_context(
        user_id="u1",
        profile_slug="mysql_metadata_assistant",
        project_slug="aion_am",
        session_id="sess2",
        sql_cache_inject_active=True,
    )
    with patch.dict(os.environ, {"AION_SQL_QM_GATE_EXPLORATION": "1"}, clear=False):
        assert (
            block_exploration_tool_if_sql_cache("memory", "search_known_sql", "sess2")
            is not None
        )
        mark_execute_sql_failed("sess2")
        assert (
            block_exploration_tool_if_sql_cache("memory", "search_known_sql", "sess2")
            is None
        )
    clear_sql_qm_turn_context("sess2")


def test_session_store_visible_without_contextvar() -> None:
    """Gate must work when MCP runs off the asyncio task (no ContextVar)."""
    clear_sql_qm_turn_context()
    set_sql_qm_turn_context(
        user_id="u1",
        profile_slug="mysql_metadata_assistant",
        project_slug="aion_am",
        session_id="sess3",
        sql_cache_inject_active=True,
    )
    if os.environ.get("AION_SQL_QM_GATE_EXPLORATION") == "0":
        return
    with patch.dict(os.environ, {"AION_SQL_QM_GATE_EXPLORATION": "1"}, clear=False):
        try:
            import contextvars

            tok = contextvars.ContextVar("test_empty", default=None)
            tok.set(None)
        except ImportError:
            pass
        msg = block_exploration_tool_if_sql_cache(
            "toolbox-mysql", "list_tables", "sess3"
        )
        assert msg is not None
    clear_sql_qm_turn_context("sess3")

"""Read-only navigation doc turns block MemPalace writes."""

from __future__ import annotations

from src.runtime.db_navigation_mempalace_hooks import user_requests_navigation_docs_only
from src.runtime.mempalace_tool_scope import mempalace_write_blocked_message
from src.runtime.sql_query_memory_context import (
    clear_sql_qm_turn_context,
    set_sql_qm_turn_context,
)


def test_user_requests_navigation_docs_only():
    assert user_requests_navigation_docs_only(
        "Prova a leggere la skill db_navigation_map e scrivimi il testo qui in chat"
    )
    assert not user_requests_navigation_docs_only(
        "Quanti pallet in produzione umida con SELECT su ordini_monge?"
    )


def test_mempalace_write_blocked_when_flag_off():
    set_sql_qm_turn_context(
        user_id="u",
        profile_slug="postgres_metadata_assistant",
        project_slug="default",
        session_id="s",
        mempalace_writes_allowed=False,
    )
    try:
        msg = mempalace_write_blocked_message("mempalace_add_drawer")
        assert msg and "sola lettura" in msg
        assert mempalace_write_blocked_message("mempalace_search") is None
    finally:
        clear_sql_qm_turn_context()

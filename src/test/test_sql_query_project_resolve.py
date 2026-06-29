"""SQL QueryMemory project resolution priority."""

from __future__ import annotations

from src.runtime.sql_query_project_resolve import resolve_sql_query_project


def test_request_project_wins_over_conversation() -> None:
    assert (
        resolve_sql_query_project(
            request_project="am_2_new",
            conversation_project="aion_am",
        )
        == "am_2_new"
    )


def test_conversation_fallback_when_request_missing() -> None:
    assert (
        resolve_sql_query_project(
            request_project=None,
            conversation_project="aion_am",
        )
        == "aion_am"
    )


def test_env_default_last() -> None:
    assert (
        resolve_sql_query_project(
            request_project="",
            conversation_project="",
            env_default="default",
        )
        == "default"
    )

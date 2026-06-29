"""Project context inject gating."""

from __future__ import annotations

from src.memory.project_memory_scope import should_inject_project_context


def test_skip_short_chitchat_on_default_project() -> None:
    assert (
        should_inject_project_context("Ciao come stai?", project_slug="default")
        is False
    )
    assert (
        should_inject_project_context("Hello, how are you?", project_slug="default")
        is False
    )


def test_inject_short_question_when_non_default_project() -> None:
    assert (
        should_inject_project_context(
            "Che iPhone ha Luca D'Agostaro?", project_slug="aion_am"
        )
        is True
    )


def test_inject_data_questions() -> None:
    assert should_inject_project_context("List tables in asset manager schema") is True
    assert should_inject_project_context("SELECT count(*) FROM users") is True


def test_inject_long_messages_on_default() -> None:
    long_msg = "x" * 150
    assert should_inject_project_context(long_msg, project_slug="default") is True

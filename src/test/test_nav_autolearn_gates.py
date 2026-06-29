"""Tests for MemPalace navigation auto-learn quality gates."""
from __future__ import annotations

from src.runtime.db_navigation_mempalace_hooks import (
    _build_nav_drawer_content,
    _nav_autolearn_skip_reason,
)


def test_skip_mcperror() -> None:
    assert (
        _nav_autolearn_skip_reason(
            ok=False,
            tables=[],
            error_hint="McpError: received invalid response: 5b",
            output_preview="",
        )
        == "mcperror"
    )


def test_skip_unknown_tables_on_success() -> None:
    assert (
        _nav_autolearn_skip_reason(
            ok=True,
            tables=[],
            error_hint="",
            output_preview="[]",
        )
        == "unknown_tables"
    )


def test_drawer_narrative_no_sql_block() -> None:
    room, content = _build_nav_drawer_content(
        user_request="quanti ordini",
        sql="SELECT count(*) FROM ordini o JOIN clienti c ON o.id=c.id",
        ok=True,
        output_preview="[{\"count\":1}]",
        error_hint="",
    )
    assert room == "join_paths"
    assert "SELECT" not in content
    assert "ordini" in content
    assert "QueryMemory" in content

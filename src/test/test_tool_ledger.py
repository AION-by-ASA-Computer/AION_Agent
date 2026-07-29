"""Tests for tool call ledger."""

from __future__ import annotations

import json

import pytest

from src.runtime.tool_ledger import (
    LedgerEntry,
    append_ledger_entry,
    extract_target_hint,
    ledger_path,
    render_ledger_table,
)
from src.runtime.tool_offload import offload_tool_result


@pytest.fixture
def session_id(tmp_path, monkeypatch):
    sid = "test-ledger-sess01"
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path))
    return sid


def test_extract_target_hint_from_url():
    hint = extract_target_hint(
        "web_fetch_page",
        {"url": "https://example.com/very/long/path/to/article"},
    )
    assert len(hint) <= 60
    assert "example.com" in hint


def test_append_and_render_ledger(session_id, monkeypatch):
    monkeypatch.setenv("AION_TOOL_LEDGER_ENABLED", "1")
    append_ledger_entry(
        session_id,
        LedgerEntry(
            seq=1,
            ts=1.0,
            tool="web_fetch_page",
            target="Group_A",
            ok=True,
            chars=10000,
            path="derived/tool_results/0001_web_fetch_page_x.txt",
        ),
    )
    table = render_ledger_table(session_id)
    assert "Tool trace" in table
    assert "web_fetch_page" in table
    assert "Group_A" in table
    assert ledger_path(session_id).is_file()


def test_render_collapses_old_rows(session_id, monkeypatch):
    monkeypatch.setenv("AION_TOOL_LEDGER_ENABLED", "1")
    monkeypatch.setenv("AION_TOOL_LEDGER_MAX_ROWS", "3")
    for i in range(5):
        append_ledger_entry(
            session_id,
            LedgerEntry(
                seq=i + 1,
                ts=float(i),
                tool="t",
                target=f"row{i}",
                ok=True,
                chars=100,
                path=None,
            ),
        )
    table = render_ledger_table(session_id)
    assert "earlier calls omitted" in table
    assert "row4" in table


def test_ledger_disabled_returns_empty(session_id, monkeypatch):
    monkeypatch.setenv("AION_TOOL_LEDGER_ENABLED", "0")
    append_ledger_entry(
        session_id,
        LedgerEntry(
            seq=1,
            ts=1.0,
            tool="x",
            target="y",
            ok=True,
            chars=1,
        ),
    )
    assert render_ledger_table(session_id) == ""


def test_offload_appends_ledger(session_id, monkeypatch):
    monkeypatch.setenv("AION_TOOL_OFFLOAD_ENABLED", "1")
    monkeypatch.setenv("AION_TOOL_LEDGER_ENABLED", "1")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_MIN_CHARS", "50")
    offload_tool_result(
        "data" * 50,
        session_id=session_id,
        tool_name="web_fetch_page",
        arguments={"url": "https://wiki.example/Group_B"},
    )
    path = ledger_path(session_id)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["tool"] == "web_fetch_page"
    assert row["path"] is not None
    assert "Group_B" in row["target"] or "wiki" in row["target"]

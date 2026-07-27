"""Tests for tool result offloading."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.runtime.tool_offload import (
    OffloadedResult,
    offload_tool_result,
    process_tool_result_for_context,
    sanitize_slug,
)
from src.session_workspace import session_root


@pytest.fixture
def session_id(tmp_path, monkeypatch):
    sid = "test-offload-sess01"
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path))
    return sid


def test_sanitize_slug_strips_unsafe():
    assert "passwd" in sanitize_slug("../../etc/passwd")
    assert "/" not in sanitize_slug("foo/bar")


def test_offload_below_threshold_returns_inline(session_id, monkeypatch):
    monkeypatch.setenv("AION_TOOL_OFFLOAD_ENABLED", "1")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_MIN_CHARS", "8000")
    monkeypatch.setenv("AION_TOOL_LEDGER_ENABLED", "0")
    small = "hello" * 10
    out = offload_tool_result(
        small,
        session_id=session_id,
        tool_name="web_fetch_page",
    )
    assert not out.offloaded
    assert out.text == small
    assert out.path is None


def test_offload_above_threshold_writes_file(session_id, monkeypatch):
    monkeypatch.setenv("AION_TOOL_OFFLOAD_ENABLED", "1")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_MIN_CHARS", "100")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_PREVIEW_CHARS", "50")
    monkeypatch.setenv("AION_TOOL_LEDGER_ENABLED", "0")
    big = "x" * 500
    out = offload_tool_result(
        big,
        session_id=session_id,
        tool_name="web_fetch_page",
        call_id="call-abc",
    )
    assert out.offloaded
    assert out.path is not None
    assert out.path.startswith("derived/tool_results/")
    full = session_root(session_id) / out.path
    assert full.is_file()
    assert full.read_text(encoding="utf-8") == big
    assert "[AION offload]" in out.text
    assert "sandbox_read_file_chunk" in out.text
    assert 'relative_root="derived"' in out.text
    assert "glob_filter=\"tool_results/*.txt\"" in out.text
    assert "derived/tool_results\"" not in out.text.split("grep")[1] if "grep" in out.text else True
    assert out.text[:200].count("x") <= 60


def test_offload_excludes_web_search(session_id, monkeypatch):
    monkeypatch.setenv("AION_TOOL_OFFLOAD_ENABLED", "1")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_MIN_CHARS", "10")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_EXCLUDE", "web_search")
    big = "y" * 500
    out = offload_tool_result(
        big,
        session_id=session_id,
        tool_name="web_search",
    )
    assert not out.offloaded
    assert out.text == big


def test_offload_invalid_session_falls_back(monkeypatch):
    monkeypatch.setenv("AION_TOOL_OFFLOAD_ENABLED", "1")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_MIN_CHARS", "10")
    big = "z" * 500
    out = offload_tool_result(
        big,
        session_id="",
        tool_name="web_fetch_page",
    )
    assert not out.offloaded


def test_offload_store_cap_prunes_oldest(session_id, monkeypatch):
    monkeypatch.setenv("AION_TOOL_OFFLOAD_ENABLED", "1")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_MIN_CHARS", "10")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_MAX_TOTAL_MB", "0.00005")
    monkeypatch.setenv("AION_TOOL_LEDGER_ENABLED", "0")
    offload_tool_result("a" * 500, session_id=session_id, tool_name="t1", seq=1)
    offload_tool_result("b" * 500, session_id=session_id, tool_name="t2", seq=2)
    store = session_root(session_id) / "derived" / "tool_results"
    txt_files = list(store.glob("*.txt"))
    assert len(txt_files) <= 1


def test_process_tool_result_fallback_truncate(session_id, monkeypatch):
    monkeypatch.setenv("AION_TOOL_OFFLOAD_ENABLED", "0")
    monkeypatch.setenv("AION_TOOL_RESULT_MAX_CHARS", "200")
    big = "q" * 5000
    text, details = process_tool_result_for_context(
        big,
        session_id=session_id,
        tool_name="mail_fetch",
    )
    assert details is None
    assert len(text) < len(big)
    assert "troncato" in text.lower()


def test_offload_excludes_sandbox_read_file_chunk(session_id, monkeypatch):
    monkeypatch.setenv("AION_TOOL_OFFLOAD_ENABLED", "1")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_MIN_CHARS", "10")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_EXCLUDE", "web_search,sandbox_read_file_chunk")
    big = "chunk " * 2000
    out = offload_tool_result(
        big,
        session_id=session_id,
        tool_name="sandbox_read_file_chunk",
        arguments={"relative_path": "derived/tool_results/0001_x.txt"},
    )
    assert not out.offloaded
    assert out.text == big


def test_smart_preview_prefers_match_section(session_id, monkeypatch):
    monkeypatch.setenv("AION_TOOL_OFFLOAD_ENABLED", "1")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_MIN_CHARS", "100")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_PREVIEW_CHARS", "120")
    monkeypatch.setenv("AION_TOOL_LEDGER_ENABLED", "0")
    intro = "Group A intro and standings table. " * 40
    payload = (
        f"```toon\nurl: \"https://en.wikipedia.org/wiki/Group_A\"\ntext: |\n"
        f"{intro}All times listed are local. Mexico beat South Africa 2–1 in the opener.\n"
        + ("more text " * 80)
        + "\n```"
    )
    out = offload_tool_result(
        payload,
        session_id=session_id,
        tool_name="web_fetch_page",
    )
    assert out.offloaded
    assert "2–1" in out.text or "2-1" in out.text
    assert "All times listed" in out.text


def test_preview_is_exact_prefix(session_id, monkeypatch):
    monkeypatch.setenv("AION_TOOL_OFFLOAD_ENABLED", "1")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_MIN_CHARS", "100")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_PREVIEW_CHARS", "80")
    payload = "PREVIEW_START" + ("m" * 400)
    out = offload_tool_result(
        payload,
        session_id=session_id,
        tool_name="web_fetch_page",
    )
    assert out.offloaded
    assert "PREVIEW_START" in out.text
    assert payload[:80] in out.text

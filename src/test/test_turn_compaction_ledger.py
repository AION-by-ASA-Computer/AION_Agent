"""Mid-turn compaction includes ledger/offload pointers."""

from __future__ import annotations

from src.runtime.turn_compaction import _append_ledger_offload_context


def test_append_ledger_offload_context_includes_path(monkeypatch):
    monkeypatch.setenv("AION_TOOL_LEDGER_ENABLED", "1")
    monkeypatch.setenv("AION_TOOL_OFFLOAD_ENABLED", "1")
    from src.settings import get_settings

    get_settings.cache_clear()

    session_id = "sess-ledger-1"
    from src.runtime.tool_offload import cleanup_session_offloads

    cleanup_session_offloads(session_id)

    from src.runtime.tool_ledger import LedgerEntry, append_ledger_entry

    rel = "derived/tool_results/0001_web_fetch_page_x.txt"
    from src.session_workspace import safe_resolve

    p = safe_resolve(session_id, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x" * 9000, encoding="utf-8")
    append_ledger_entry(
        session_id,
        LedgerEntry(
            seq=1,
            ts=1.0,
            tool="web_fetch_page",
            target="https://example.com",
            ok=True,
            chars=9000,
            path=rel,
        ),
    )

    out = _append_ledger_offload_context("user: hi", session_id)
    assert "offloaded-results" in out or rel in out
    assert "web_fetch_page" in out or "tool-trace" in out

    cleanup_session_offloads(session_id)
    get_settings.cache_clear()

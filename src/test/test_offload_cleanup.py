"""cleanup_session_offloads removes derived/tool_results."""

from __future__ import annotations

from src.runtime.tool_offload import cleanup_session_offloads
from src.session_workspace import safe_resolve


def test_cleanup_session_offloads_removes_files():
    session_id = "sess-clean-1"
    rel = "derived/tool_results/0001_tool_x.txt"
    p = safe_resolve(session_id, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("payload", encoding="utf-8")
    ledger = safe_resolve(session_id, "derived/tool_results/_ledger.jsonl")
    ledger.write_text("{}\n", encoding="utf-8")

    freed = cleanup_session_offloads(session_id)
    assert freed > 0
    assert not p.exists()

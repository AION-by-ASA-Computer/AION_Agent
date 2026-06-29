"""Mutating tool dedupe must surface explicit errors, not fake success."""

import threading
import time
from unittest.mock import MagicMock, patch

import src.main as main_mod
from src.main import _aion_mcp_tool_run
from src.runtime.context import clear_context, set_context


def _run_tool(session: str = "dedupe-sess"):
    loop = MagicMock()
    loop.is_closed.return_value = False
    loop.is_running.return_value = False
    stop = threading.Event()
    set_context(session, loop, MagicMock(), stop)
    try:
        with patch("src.mcp_manager.SerializableMCPTool") as mock_cls:
            mock_cls.return_value.return_value = "ok"
            with patch("src.main.StreamSync.wait_for_sync"):
                with patch(
                    "src.main.maybe_compact_after_tool",
                    side_effect=lambda **k: k.get("result"),
                ):
                    return _aion_mcp_tool_run(
                        "sandbox",
                        "write_workspace_file",
                        session,
                        {"path": "x.txt", "content": "hi"},
                    )
    finally:
        clear_context()


def test_duplicate_mutating_call_returns_error(monkeypatch):
    monkeypatch.setattr(main_mod, "_TOOL_DEDUPE_TTL_SEC", 20.0)
    main_mod._TOOL_DEDUPE_CACHE.clear()
    first = _run_tool()
    assert "error" not in first.lower() or "ok" in first.lower()
    second = _run_tool()
    assert "duplicate" in second.lower() or "blocked" in second.lower()


def test_duplicate_allowed_after_ttl(monkeypatch):
    main_mod._TOOL_DEDUPE_CACHE.clear()
    monkeypatch.setattr(main_mod, "_TOOL_DEDUPE_TTL_SEC", 0.05)
    _run_tool("ttl-sess")
    time.sleep(0.06)
    out = _run_tool("ttl-sess")
    assert "duplicate" not in out.lower()

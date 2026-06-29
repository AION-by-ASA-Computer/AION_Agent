"""MCP tools must honour turn stop_event."""

import threading
from unittest.mock import MagicMock, patch

from src.main import _aion_mcp_tool_run
from src.runtime.context import set_context


def test_mcp_tool_returns_cancelled_when_stop_event_set():
    stop = threading.Event()
    stop.set()
    set_context("sess-1", MagicMock(), MagicMock(), stop)
    try:
        with patch("src.mcp_manager.SerializableMCPTool") as mock_tool:
            out = _aion_mcp_tool_run(
                "sandbox", "write_file", "sess-1", {"path": "a.txt"}
            )
            mock_tool.assert_not_called()
    finally:
        from src.runtime.context import clear_context

        clear_context()
    assert "cancelled" in out.lower() or "Turn cancelled" in out

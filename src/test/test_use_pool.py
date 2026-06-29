"""Regression: SerializableMCPTool must not raise NameError on _USE_POOL during hot reload."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp_manager import SerializableMCPTool, mcp_manager


def test_serializable_mcp_tool_use_pool_lookup():
    """__call__ reads _USE_POOL via getattr on module, not bare global."""
    import src.mcp_manager as mm

    assert hasattr(mm, "_USE_POOL")

    tool = SerializableMCPTool("memory", "test_tool", "sess-1")

    mock_loop = MagicMock()
    mock_future = MagicMock()
    mock_future.result.return_value = "ok"

    with (
        patch.object(mm, "_USE_POOL", True),
        patch.object(mcp_manager, "_is_stdio_server", return_value=False),
        patch(
            "src.mcp_manager.asyncio.run_coroutine_threadsafe", return_value=mock_future
        ),
        patch("src.main._GLOBAL_LOOP", mock_loop, create=True),
    ):
        out = tool()
    assert out == "ok"

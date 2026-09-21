"""
Unit tests for MCP tool filtering & dynamic tool selection.
Verifies that:
1. `build_mcp_tools` respects `enabled_tools` in ordinary chat sessions.
2. `build_mcp_tools` bypasses `enabled_tools` during probe sessions (e.g. `mcp-probe`).
3. Endpoint `/admin/mcp/{name}/tools-config` updates `enabled_tools` and triggers cache invalidation.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import src.aion_env  # noqa: F401
from src.main import build_mcp_tools
from src.api.admin import set_mcp_tools_config, ToolsConfigBody


class DummyMcpTool:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.inputSchema = {"type": "object", "properties": {}}


class DummyToolsResult:
    def __init__(self, tools):
        self.tools = tools


def test_build_mcp_tools_filters_when_configured():
    async def _test():
        raw_tools = [
            DummyMcpTool(name="get_dashboard", description="Fetch a dashboard"),
            DummyMcpTool(name="delete_dashboard", description="Delete a dashboard"),
            DummyMcpTool(name="list_alerts", description="List active alerts"),
            DummyMcpTool(name="delete_alert", description="Delete an alert"),
        ]

        mock_session = AsyncMock()
        mock_session.list_tools.return_value = DummyToolsResult(tools=raw_tools)

        # Server config with enabled_tools list (only 2 enabled)
        server_config = {
            "command": "npx",
            "args": ["-y", "mcp-test-server"],
            "enabled_tools": ["get_dashboard", "list_alerts"],
        }

        with patch("src.main.mcp_manager.session_context") as mock_session_ctx:
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            # 1. Normal session: only 2 enabled tools should be returned
            tools_chat = await build_mcp_tools(
                "test_server",
                server_config,
                session_id="chat-user-123",
                user_id="user_1",
            )
            assert len(tools_chat) == 2
            tool_names = [t.name for t in tools_chat]
            assert "get_dashboard" in tool_names
            assert "list_alerts" in tool_names
            assert "delete_dashboard" not in tool_names

            # 2. Probe session: all 4 tools should be returned
            tools_probe = await build_mcp_tools(
                "test_server",
                server_config,
                session_id="mcp-probe",
                user_id="user_1",
            )
            assert len(tools_probe) == 4
            probe_names = [t.name for t in tools_probe]
            assert "get_dashboard" in probe_names
            assert "delete_dashboard" in probe_names
            assert "list_alerts" in probe_names
            assert "delete_alert" in probe_names

    asyncio.run(_test())


def test_set_mcp_tools_config_endpoint():
    async def _test():
        dummy_registry = {
            "grafana": {
                "command": "npx",
                "args": ["-y", "@grafana/mcp-server"],
                "enabled_tools": ["query_metrics"],
            }
        }

        with (
            patch("src.api.admin.mcp_manager._registry", dummy_registry),
            patch("src.api.admin.mcp_manager._registry_local", dummy_registry),
            patch("src.api.admin.mcp_manager.load_registry"),
            patch("src.api.admin.mcp_manager.save_registry") as mock_save,
            patch("src.api.admin.mcp_manager._rebuild_merged"),
            patch("src.main.clear_agent_cache") as mock_clear_cache,
        ):
            body = ToolsConfigBody(enabled_tools=["query_metrics", "list_dashboards"])
            res = await set_mcp_tools_config("grafana", body)

            assert res["status"] == "success"
            assert res["server_slug"] == "grafana"
            assert res["enabled_tools"] == ["query_metrics", "list_dashboards"]

            # Local registry updated in-place & persisted
            assert dummy_registry["grafana"]["enabled_tools"] == [
                "query_metrics",
                "list_dashboards",
            ]
            mock_save.assert_called_once()
            mock_clear_cache.assert_called_once()

    asyncio.run(_test())

"""PUT /admin/mcp/{name}: l'header Bearer di un remote-bridge segue la modalità
credenziali che admin-ui sta salvando, non quella ancora nel DB."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import src.aion_env  # noqa: F401
from src.api.admin import MCPUpdate, update_mcp_config

ARGS = [
    "node_modules/mcp-remote/dist/proxy.js",
    "http://localhost:8095/mcp",
    "--header",
    "Authorization: Bearer ${API_KEY}",
]
REGISTRY = {"broker": {"type": "remote-bridge", "args": ARGS, "env": {}}}


def _put(payload):
    row = SimpleNamespace(credential_mode="none")
    result = MagicMock()
    result.scalars.return_value.first.return_value = row
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.api.admin.mcp_manager._registry", REGISTRY),
        patch("src.api.admin.mcp_manager.get_server_config", return_value=REGISTRY["broker"]),
        patch("src.api.admin.mcp_manager.update_server_config", side_effect=lambda n, d: d) as upd,
        patch("src.api.admin.get_async_session_maker", return_value=lambda: ctx),
        patch("src.mcp_integration_sync.sync_mcp_server_config_from_registry", AsyncMock()),
    ):
        asyncio.run(update_mcp_config("broker", MCPUpdate(**payload)))
    return upd.call_args.args[1]


def test_switch_to_org_shared_keeps_header():
    saved = _put({"args": ARGS, "env": {"API_KEY": "tok"}, "credential_mode": "org_shared"})
    assert saved["args"] == ARGS
    assert saved["env"] == {"API_KEY": "tok"}
    assert "credential_mode" not in saved


def test_mode_none_still_strips_header():
    saved = _put({"args": ARGS, "env": {"API_KEY": "tok"}, "credential_mode": "none"})
    assert "--header" not in saved["args"]
    assert "env" not in saved


def test_without_mode_uses_db_mode():
    saved = _put({"args": ARGS})
    assert "--header" not in saved["args"]

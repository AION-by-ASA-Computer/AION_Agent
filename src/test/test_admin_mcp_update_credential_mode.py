"""PUT /admin/mcp/{name}: l'header Bearer di un remote-bridge segue la modalità
credenziali che admin-ui sta salvando, non quella ancora nel DB; i secret
condivisi modificati da Configura finiscono nello store cifrato e i worker MCP
in pool vengono riavviati con la nuova configurazione."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import src.aion_env  # noqa: F401
from src.api.admin import MCPUpdate, update_mcp_config

ARGS = [
    "node_modules/mcp-remote/dist/proxy.js",
    "http://localhost:8095/mcp",
    "--header",
    "Authorization: Bearer ${API_KEY}",
]
REGISTRY = {
    "broker": {"type": "remote-bridge", "args": ARGS, "env": {}},
    "db2": {"command": "npx", "args": ["-y", "mcp-server-db2i"], "env": {}},
}


def _put(payload, *, name="broker", db_mode="none"):
    """Run the endpoint with registry/DB mocked; return (saved update, mocks)."""
    row = SimpleNamespace(credential_mode=db_mode)
    result = MagicMock()
    result.scalars.return_value.first.return_value = row
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    set_cred = AsyncMock()
    invalidate = AsyncMock()

    with (
        patch("src.api.admin.mcp_manager._registry", REGISTRY),
        patch(
            "src.api.admin.mcp_manager.get_server_config",
            return_value=REGISTRY[name],
        ),
        patch(
            "src.api.admin.mcp_manager.update_server_config", side_effect=lambda n, d: d
        ) as upd,
        patch("src.api.admin.get_async_session_maker", return_value=lambda: ctx),
        patch(
            "src.mcp_integration_sync.sync_mcp_server_config_from_registry", AsyncMock()
        ),
        patch("src.runtime.credential_store.set_credential", set_cred),
        patch("src.api.admin._invalidate_mcp_runtime", invalidate),
    ):
        asyncio.run(update_mcp_config(name, MCPUpdate(**payload)))
    return upd.call_args.args[1], set_cred, invalidate


def test_switch_to_org_shared_keeps_header():
    """Switching to org_shared keeps the Bearer header; the token moves to the store."""
    saved, set_cred, _ = _put(
        {"args": ARGS, "env": {"API_KEY": "tok"}, "credential_mode": "org_shared"}
    )
    assert saved["args"] == ARGS
    assert saved["env"] == {"API_KEY": "${API_KEY}"}
    assert "credential_mode" not in saved
    set_cred.assert_has_awaits(
        [
            call("default", "broker", "API_KEY", "tok", tenant_id="default"),
            call("org_shared", "broker", "API_KEY", "tok", tenant_id="default"),
        ]
    )


def test_mode_none_still_strips_header():
    """credential_mode=none drops env and the Bearer header of a remote bridge."""
    saved, _, _ = _put(
        {"args": ARGS, "env": {"API_KEY": "tok"}, "credential_mode": "none"}
    )
    assert "--header" not in saved["args"]
    assert "env" not in saved


def test_without_mode_uses_db_mode():
    """Without credential_mode in the body the mode stored in the DB applies."""
    saved, _, _ = _put({"args": ARGS})
    assert "--header" not in saved["args"]


def test_org_shared_secret_edited_in_configura_goes_to_store():
    """A password typed in Configura is encrypted, the registry keeps a placeholder."""
    saved, set_cred, _ = _put(
        {
            "env": {
                "DB2I_HOSTNAME": "192.168.10.241",
                "DB2I_USERNAME": "leggisql",
                "DB2I_PASSWORD": "newpass",
            }
        },
        name="db2",
        db_mode="org_shared",
    )
    assert saved["env"] == {
        "DB2I_HOSTNAME": "192.168.10.241",
        "DB2I_USERNAME": "leggisql",
        "DB2I_PASSWORD": "${DB2I_PASSWORD}",
    }
    set_cred.assert_has_awaits(
        [
            call("default", "db2", "DB2I_PASSWORD", "newpass", tenant_id="default"),
            call("org_shared", "db2", "DB2I_PASSWORD", "newpass", tenant_id="default"),
        ]
    )


def test_org_shared_unchanged_placeholder_is_not_rewritten():
    """Saving without touching the secret keeps the placeholder and the stored value."""
    saved, set_cred, _ = _put(
        {"env": {"DB2I_PASSWORD": "${DB2I_PASSWORD}"}},
        name="db2",
        db_mode="org_shared",
    )
    assert saved["env"] == {"DB2I_PASSWORD": "${DB2I_PASSWORD}"}
    set_cred.assert_not_awaited()


def test_save_restarts_pooled_workers():
    """Every save invalidates the cached agents and pooled workers of the server."""
    _, _, invalidate = _put(
        {"env": {"DB2I_SCHEMA": "GESTDAT"}}, name="db2", db_mode="org_shared"
    )
    invalidate.assert_awaited_once_with("db2")

"""Deleting an MCP server leaves no orphan rows behind (integrity banner stays clean).

Regression for the Hub showing "Policy DB senza voce nel registry" / "Credenziali
utente senza MCP nel registry" after a deletion: stopping the server's pooled
worker raised CancelledError into the admin request, which aborted after the
registry removal and before the DB cleanup (500 "No response returned"); retries
then answered 404 because the server was no longer in the registry.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.aion_env  # noqa: F401
from src.mcp_manager import MCPManager, mcp_manager


def _running_worker():
    """A pooled-worker stand-in whose task runs until cancelled."""
    from src.mcp_manager import MCPStdioWorker

    worker = MCPStdioWorker.__new__(MCPStdioWorker)
    worker._chat_session_id = ""
    worker._container_jail = False
    worker._queue = asyncio.Queue()
    worker._task = asyncio.create_task(asyncio.sleep(3600))
    return worker


def test_restart_workers_does_not_cancel_the_caller():
    """Stopping a running worker must not propagate its CancelledError to the caller."""

    async def scenario():
        manager = MCPManager.__new__(MCPManager)
        manager._pool_lock = asyncio.Lock()
        manager._pool = {("sess", "srv"): _running_worker()}
        stopped = await manager.restart_workers_for_server("srv")
        return stopped, "still running"

    stopped, marker = asyncio.run(scenario())
    assert stopped == 1 and marker == "still running"


def _db_session(rowcount: int):
    result = MagicMock()
    result.rowcount = rowcount
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


def _delete(name, *, registry, user_rows, policy_rows, invalidate=None, custom_files=False):
    """Run DELETE /admin/mcp/{name} with registry, profiles and DB mocked."""
    from src.api import admin as admin_api

    ctx, session = _db_session(policy_rows)
    delete_user_data = AsyncMock(return_value={"credentials_deleted": user_rows, "preferences_deleted": 0})
    profiles = SimpleNamespace(load_all=lambda: None, _profiles={})
    with (
        patch.object(mcp_manager, "_registry_base", {}),
        patch.object(mcp_manager, "_registry", dict(registry)),
        patch.object(mcp_manager, "delete_server", side_effect=lambda n: n in registry),
        patch("src.agent_profile.profile_manager", profiles),
        patch("src.api.admin.get_async_session_maker", return_value=lambda: ctx),
        patch("src.runtime.mcp_integration_integrity.delete_mcp_user_data", delete_user_data),
        patch("src.api.admin._invalidate_mcp_runtime", invalidate or AsyncMock()),
        patch("src.mcp_custom.install.has_custom_artifacts", return_value=custom_files),
        patch("src.api.admin._remove_market_mcp_artifacts"),
    ):
        auth = SimpleNamespace(identifier="admin", user_row_id=None)
        out = asyncio.run(admin_api.delete_mcp(name, auth=auth))
    return out, delete_user_data, session


def test_delete_cleans_db_even_if_stopping_workers_fails():
    """The DB rows go first: a failing worker shutdown cannot orphan them anymore."""
    out, delete_user_data, session = _delete(
        "srv",
        registry={"srv": {"command": "npx"}},
        user_rows=2,
        policy_rows=1,
        invalidate=AsyncMock(side_effect=RuntimeError("worker stuck")),
    )
    assert out["status"] == "success"
    delete_user_data.assert_awaited_once_with("srv")
    assert session.execute.await_count == 1  # McpServerConfig row deleted
    assert out["cleanup"]["policy_deleted"] == 1


def test_second_delete_cleans_leftovers_of_an_interrupted_one():
    """Server already out of the registry but rows left behind: DELETE cleans them (200)."""
    out, _, _ = _delete("srv", registry={}, user_rows=2, policy_rows=1)
    assert out["status"] == "success"
    assert out["cleanup"]["credentials_deleted"] == 2


def test_delete_unknown_server_is_404():
    """Nothing in the registry, the DB or on disk: still a 404."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _delete("ghost", registry={}, user_rows=0, policy_rows=0)
    assert exc.value.status_code == 404

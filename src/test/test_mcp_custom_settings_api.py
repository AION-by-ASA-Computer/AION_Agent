"""Admin -> Settings -> MCPs: custom MCP variables saved through POST /admin/settings.

Covers the hot reload (only AION_CUSTOM_MCP_* changed: no backend restart, custom
workers restarted) and the refusal to change AION_CUSTOM_MCP_ALLOW_UNSANDBOXED from
the web panel (src/api/settings_api.py).
"""

from __future__ import annotations

import asyncio
from typing import Dict
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import src.aion_env  # noqa: F401
from src.api import settings_api


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    """In-memory env store: _parse_env/load_base_env read it, _write_env records writes."""
    state: Dict[str, Dict[str, str]] = {"current": {"AION_MODEL": "m", "AION_CUSTOM_MCP_ENABLED": "0"}, "written": {}}
    monkeypatch.setattr(settings_api, "_parse_env", lambda: dict(state["current"]))
    monkeypatch.setattr(settings_api, "load_base_env", lambda **_k: dict(state["current"]))
    monkeypatch.setattr(settings_api, "_write_env", lambda merged: state["written"].update(merged))
    monkeypatch.setattr(settings_api, "_reload_env", lambda: None)
    monkeypatch.setattr(settings_api, "_is_container_env", lambda: True)
    exit_mock = AsyncMock()
    workers_mock = AsyncMock()
    monkeypatch.setattr(settings_api, "_deferred_exit", exit_mock)
    monkeypatch.setattr(settings_api, "_restart_custom_mcp_workers", workers_mock)
    return state, exit_mock, workers_mock


def _post(settings: Dict[str, str]):
    async def go():
        out = await settings_api.update_settings(settings_api.SettingsUpdate(settings=settings))
        await asyncio.sleep(0)  # let scheduled tasks run
        return out

    return asyncio.run(go())


def test_custom_mcp_change_needs_no_restart(env):
    """Only AION_CUSTOM_MCP_* changed: saved, no container restart, custom workers restarted."""
    state, exit_mock, workers_mock = env
    out = _post({"AION_MODEL": "m", "AION_CUSTOM_MCP_ENABLED": "1", "AION_CUSTOM_MCP_MEMORY": "1g"})
    assert out["restarting"] is False
    assert state["written"]["AION_CUSTOM_MCP_ENABLED"] == "1"
    exit_mock.assert_not_awaited()
    workers_mock.assert_awaited_once()


def test_other_change_still_restarts(env):
    """A non-MCP key keeps the usual container restart."""
    _state, exit_mock, _workers = env
    out = _post({"AION_MODEL": "other", "AION_CUSTOM_MCP_ENABLED": "0"})
    assert out["restarting"] is True
    exit_mock.assert_awaited_once()


def test_unsandboxed_cannot_be_set_from_panel(env):
    """Running custom servers without the jail stays a .env-only decision."""
    state, _exit, _workers = env
    with pytest.raises(HTTPException) as err:
        _post({"AION_MODEL": "m", "AION_CUSTOM_MCP_ALLOW_UNSANDBOXED": "1"})
    assert err.value.status_code == 400
    assert state["written"] == {}

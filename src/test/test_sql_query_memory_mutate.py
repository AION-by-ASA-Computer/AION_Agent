"""SQL QueryMemory update/delete — user_id, project scope, error messages."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.memory.sql_query_memory.service import SqlQueryMemoryService


def test_format_mutation_error_not_found():
    msg = SqlQueryMemoryService.format_mutation_error("not_found", entry_id=22)
    assert "id=22" in msg
    assert "not found" in msg.lower()


def test_format_mutation_error_wrong_project():
    msg = SqlQueryMemoryService.format_mutation_error(
        "wrong_project",
        entry_id=22,
        project_slug="am_2_new",
        entry_project="aion_am",
    )
    assert "am_2_new" in msg
    assert "aion_am" in msg
    assert "sql_memory_list_saved" in msg


@pytest.mark.anyio
async def test_delete_entry_passes_user_and_project_to_validator():
    svc = SqlQueryMemoryService()
    mock_session = AsyncMock()
    mock_row = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_row)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    with patch.object(svc, "session_maker") as sm, patch.object(
        svc, "_validate_entry_for_user", new_callable=AsyncMock
    ) as validate:
        sm.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        sm.return_value.__aexit__ = AsyncMock(return_value=False)
        validate.return_value = (mock_row, MagicMock(slug="am_2_new"), "")

        ok, err = await svc.delete_entry(
            22,
            user_id="luca",
            tenant_id="default",
            profile_slug="mysql_metadata_assistant",
            project_slug="am_2_new",
        )

    assert ok is True
    assert err == ""
    validate.assert_awaited_once()
    call_kw = validate.await_args.kwargs
    assert call_kw["user_id"] == "luca"
    assert call_kw["project_slug"] == "am_2_new"


@pytest.mark.anyio
async def test_update_entry_returns_no_fields_when_empty():
    svc = SqlQueryMemoryService()
    ok, err = await svc.update_entry(22, user_id="luca")
    assert ok is False
    assert err == "no_fields"


def test_mcp_delete_passes_user_context(monkeypatch):
    import asyncio

    import mcp_servers_std.query_memory.server as qm_server

    captured: dict = {}

    async def fake_delete(entry_id, **kwargs):
        captured.update(kwargs)
        return True, ""

    async def fake_active():
        return "am_2_new"

    async def _run():
        monkeypatch.setattr(qm_server.sql_query_memory, "delete_entry", fake_delete)
        monkeypatch.setattr(qm_server, "_active_sql_project", fake_active)
        monkeypatch.setenv("AION_CURRENT_USER_ID", "luca")
        monkeypatch.setenv("AION_CURRENT_TENANT_ID", "default")
        return await qm_server.delete_sql_memory_entry(24)

    result = asyncio.run(_run())
    assert "deleted" in result.lower()
    assert captured["user_id"] == "luca"
    assert captured["project_slug"] == "am_2_new"


def test_mcp_delete_accepts_project_kwarg(monkeypatch):
    import asyncio

    import mcp_servers_std.query_memory.server as qm_server

    captured: dict = {}

    async def fake_delete(entry_id, **kwargs):
        captured.update(kwargs)
        return True, ""

    async def _run():
        monkeypatch.setattr(qm_server.sql_query_memory, "delete_entry", fake_delete)
        return await qm_server.delete_sql_memory_entry(22, project="am_2_new")

    result = asyncio.run(_run())
    assert "deleted" in result.lower()
    assert captured["project_slug"] == "am_2_new"


def test_mcp_update_surfaces_wrong_project_message(monkeypatch):
    import asyncio

    import mcp_servers_std.query_memory.server as qm_server

    async def fake_update(entry_id, **kwargs):
        return False, "wrong_project"

    async def fake_active():
        return "am_2_new"

    async def fake_resolve(code, *, entry_id, project_slug=None):
        return SqlQueryMemoryService.format_mutation_error(
            code,
            entry_id=entry_id,
            project_slug=project_slug,
            entry_project="aion_am",
        )

    async def _run():
        monkeypatch.setattr(qm_server.sql_query_memory, "update_entry", fake_update)
        monkeypatch.setattr(qm_server, "_active_sql_project", fake_active)
        monkeypatch.setattr(
            qm_server.sql_query_memory,
            "resolve_mutation_error_message",
            fake_resolve,
        )
        return await qm_server.update_sql_memory_entry(22, sql="select 1")

    result = asyncio.run(_run())
    assert "aion_am" in result
    assert "am_2_new" in result

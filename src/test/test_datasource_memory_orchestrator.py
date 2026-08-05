"""Datasource memory orchestrator without MemPalace nav hooks."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.runtime.datasource_memory_orchestrator import (
    _pre_turn_datasource_memory_orchestrator,
)
from src.runtime.hooks import HookContext


@pytest.mark.asyncio
async def test_orchestrator_injects_active_project(monkeypatch):
    monkeypatch.setenv("AION_DATASOURCE_MEMORY_ORCHESTRATOR", "1")
    ctx = HookContext(
        event="pre_turn",
        tenant_id="default",
        conversation_id="sess-1",
        user_id="u1",
        profile="postgres_metadata_assistant",
        payload={
            "user_input": "show sales",
            "sql_query_project": "acme",
        },
    )
    with patch(
        "src.runtime.query_memory_hooks._run_pre_turn_sql_query_memory",
        new_callable=AsyncMock,
    ) as sql_mock:
        await _pre_turn_datasource_memory_orchestrator(ctx)
        sql_mock.assert_awaited_once()
    assert "ACTIVE_PROJECT: acme" in (ctx.modified_payload or {}).get(
        "project_context_inject", ""
    )

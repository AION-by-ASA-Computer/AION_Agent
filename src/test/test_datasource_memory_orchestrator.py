"""Datasource memory orchestrator pre_turn inject."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.runtime.hooks import HookContext, hook_registry


@pytest.fixture(autouse=True)
def _clear_hooks():
    yield


def test_orchestrator_calls_sql_and_nav(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.runtime.datasource_memory_orchestrator as orch
    from src.runtime import query_memory_hooks
    from src.runtime import db_navigation_mempalace_hooks

    sql_mock = AsyncMock()
    nav_mock = AsyncMock()
    monkeypatch.setattr(query_memory_hooks, "_run_pre_turn_sql_query_memory", sql_mock)
    monkeypatch.setattr(
        db_navigation_mempalace_hooks, "_pre_turn_mempalace_navigation", nav_mock
    )

    async def _run() -> HookContext:
        ctx = HookContext(
            event="pre_turn",
            tenant_id="default",
            conversation_id="sess-orch-1",
            user_id="u1",
            profile="mysql_metadata_assistant",
            payload={"user_input": "Che pc ha Mario?", "sql_query_project": "aion_am"},
        )
        with patch(
            "src.runtime.datasource_memory_orchestrator.profile_wants_sql_query_memory_by_slug",
            return_value=True,
        ):
            with patch(
                "src.memory.project_memory_scope.project_context_block_async",
                new=AsyncMock(return_value="[project_context] test"),
            ):
                with patch(
                    "src.memory.project_memory_scope.should_inject_project_context",
                    return_value=True,
                ):
                    with patch(
                        "src.runtime.sql_query_memory_context.format_session_entity_cache_block",
                        return_value="",
                    ):
                        await orch._pre_turn_datasource_memory_orchestrator(ctx)
        return ctx

    ctx = asyncio.run(_run())
    sql_mock.assert_awaited_once()
    nav_mock.assert_awaited_once()
    mod = ctx.modified_payload or {}
    assert "project_context_inject" in mod

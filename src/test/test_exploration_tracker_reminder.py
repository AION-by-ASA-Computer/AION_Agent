"""Exploration tracker reminder across turns."""

from __future__ import annotations

import pytest

from src.runtime.exploration_tracker import (
    _trackers,
    begin_exploration_turn,
    finish_exploration_turn,
    record_exploration_tool,
)
from src.runtime.hooks import HookContext, hook_registry


@pytest.fixture(autouse=True)
def clear_trackers():
    _trackers.clear()
    yield
    _trackers.clear()


def test_reminder_after_explore_without_save() -> None:
    sid = "sess-explore-1"
    begin_exploration_turn(sid)
    record_exploration_tool(
        session_id=sid,
        tool_name="toolbox-mysql-list_tables",
        event_type="tool_end",
        output='{"schema_name":"aion_am"}',
        profile_slug="mysql_metadata_assistant",
    )
    record_exploration_tool(
        session_id=sid,
        tool_name="toolbox-mysql-execute_sql",
        event_type="tool_end",
        output='{"modello":"IPHONE 15"}',
        profile_slug="mysql_metadata_assistant",
    )
    finish_exploration_turn(sid)
    reminder = begin_exploration_turn(sid)
    assert reminder is not None
    assert "did not persist" in reminder


def test_no_reminder_when_saved() -> None:
    sid = "sess-explore-2"
    begin_exploration_turn(sid)
    record_exploration_tool(
        session_id=sid,
        tool_name="execute_sql",
        event_type="tool_end",
        output='[{"x":1}]',
        profile_slug="mysql_metadata_assistant",
    )
    record_exploration_tool(
        session_id=sid,
        tool_name="mempalace_add_drawer",
        event_type="tool_end",
        output='{"ok":true}',
        profile_slug="mysql_metadata_assistant",
    )
    finish_exploration_turn(sid)
    assert begin_exploration_turn(sid) is None


def test_pre_turn_hook_injects_reminder() -> None:
    import asyncio

    sid = "sess-explore-3"
    begin_exploration_turn(sid)
    record_exploration_tool(
        session_id=sid,
        tool_name="list_tables",
        event_type="tool_end",
        output="[]",
        profile_slug="mysql_metadata_assistant",
    )
    finish_exploration_turn(sid)

    import src.runtime.exploration_tracker  # noqa: F401
    from src.runtime.exploration_tracker import register_exploration_tracker_hooks

    register_exploration_tracker_hooks()

    async def _run() -> HookContext:
        ctx = HookContext(
            event="pre_turn",
            tenant_id="default",
            conversation_id=sid,
            user_id="u1",
            profile="mysql_metadata_assistant",
            payload={"user_input": "test"},
        )
        return await hook_registry.dispatch("pre_turn", ctx)

    ctx = asyncio.run(_run())
    mod = ctx.modified_payload or {}
    assert "exploration_reminder" in mod
    assert "persist" in mod["exploration_reminder"].lower()

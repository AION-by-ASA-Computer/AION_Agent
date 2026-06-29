"""Datasource memory workflow prompt and reminders."""

from __future__ import annotations

from src.runtime.datasource_memory_mode import (
    build_datasource_memory_system_prompt,
    maybe_append_same_turn_reminder,
)
from src.runtime.exploration_tracker import (
    _trackers,
    begin_exploration_turn,
    needs_persist_reminder,
    record_exploration_tool,
)


def test_prompt_contains_workflow_steps() -> None:
    prompt = build_datasource_memory_system_prompt()
    assert "DATASOURCE MEMORY WORKFLOW" in prompt
    assert "SEARCH" in prompt
    assert "PERSIST" in prompt
    assert "save_successful_query" in prompt


def test_wren_prompt_mentions_sandbox_exec() -> None:
    from types import SimpleNamespace

    profile = SimpleNamespace(skills=["wren"], wren_project_path="wren/alibr_db")
    prompt = build_datasource_memory_system_prompt(profile)
    assert "Wren Engine" in prompt
    assert "sandbox_exec_allowlisted" in prompt
    assert "toolbox-postgres" in prompt


def test_same_turn_reminder_after_explore() -> None:
    _trackers.clear()
    sid = "sess-reminder-1"
    begin_exploration_turn(sid)
    record_exploration_tool(
        session_id=sid,
        tool_name="execute_sql",
        event_type="tool_end",
        output='[{"serial":"ABC"}]',
        profile_slug="mysql_metadata_assistant",
    )
    assert needs_persist_reminder(sid)
    out = maybe_append_same_turn_reminder(
        session_id=sid,
        profile_slug="mysql_metadata_assistant",
        tool_name="execute_sql",
        event_type="tool_end",
        output='[{"serial":"ABC"}]',
    )
    assert "datasource_persist_reminder" in out
    _trackers.clear()


def test_no_reminder_after_save() -> None:
    _trackers.clear()
    sid = "sess-reminder-2"
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
        tool_name="sql_memory_save",
        event_type="tool_end",
        output='{"ok":true}',
        profile_slug="mysql_metadata_assistant",
    )
    assert not needs_persist_reminder(sid)
    _trackers.clear()

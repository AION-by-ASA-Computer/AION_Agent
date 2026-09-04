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


def test_same_turn_reminder_after_explore(monkeypatch) -> None:
    monkeypatch.setenv("AION_PROFILES_STD_DIR", "config_std/profiles")
    monkeypatch.setenv("AION_DATASOURCE_PERSIST_REMINDER", "1")
    monkeypatch.setenv("AION_DATASOURCE_MEMORY_WORKFLOW", "1")
    from src.agent_profile import profile_manager, profiles_std_path

    profile_manager.std_path = profiles_std_path()
    profile_manager.write_path = profiles_std_path()
    profile_manager.invalidate()
    profile_manager.load_all()
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

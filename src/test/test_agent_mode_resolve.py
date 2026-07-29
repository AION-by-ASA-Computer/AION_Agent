from src.runtime.agent_mode_resolve import resolve_agent_mode


def test_internal_trigger_forces_normal_even_when_plan_requested():
    assert (
        resolve_agent_mode("plan", plan_mode=True, message_source="internal_trigger")
        == "normal"
    )


def test_plan_mode_flag_still_works_for_user_input():
    assert (
        resolve_agent_mode("normal", plan_mode=True, message_source="user_input")
        == "plan"
    )


def test_plan_mode_false_downgrades_plan():
    assert (
        resolve_agent_mode("plan", plan_mode=False, message_source="user_input")
        == "normal"
    )


def test_long_run_requires_flag():
    assert resolve_agent_mode("long_run", message_source="user_input") == "normal"


def test_long_run_when_enabled(monkeypatch):
    monkeypatch.setenv("AION_LONG_RUN_ENABLED", "1")
    assert resolve_agent_mode("long_run", message_source="user_input") == "long_run"


def test_internal_trigger_forces_normal_even_for_long_run(monkeypatch):
    monkeypatch.setenv("AION_LONG_RUN_ENABLED", "1")
    assert resolve_agent_mode("long_run", message_source="internal_trigger") == "normal"

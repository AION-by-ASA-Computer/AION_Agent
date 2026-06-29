"""Plan Mode guard must not block post-approval execution (internal_trigger)."""

from src.runtime.agent_mode_resolve import resolve_agent_mode
from src.runtime.plan_mode_guard import plan_mode_response_valid


def test_internal_trigger_resolves_normal_despite_env_plan_default(monkeypatch):
    monkeypatch.setenv("AION_DEFAULT_AGENT_MODE", "plan")
    assert (
        resolve_agent_mode("plan", plan_mode=True, message_source="internal_trigger")
        == "normal"
    )


def test_execution_response_without_plan_tag_is_invalid_in_plan_mode_only():
    body = "Eseguo task_01: ricerca web su OCR.\n"
    ok, reason = plan_mode_response_valid(body)
    assert not ok
    assert reason == "missing_plan_tag"

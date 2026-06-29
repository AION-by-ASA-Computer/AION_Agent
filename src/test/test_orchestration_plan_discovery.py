"""Orchestration plan discovery: active plan resolution without workspace files."""

import pytest

from src.runtime import orchestration_tools as ot


@pytest.mark.anyio
async def test_resolve_active_plan_id_prefers_approved(monkeypatch):
    async def fake_list(session_id, *, limit=20):
        assert session_id == "sess-a"
        return [
            {"plan_id": "execution_plan_draft1", "status": "draft_pending", "revision": 2},
            {"plan_id": "execution_plan_main", "status": "approved", "revision": 5},
        ]

    monkeypatch.setattr("src.runtime.orchestration_db.list_plans_for_session", fake_list)
    assert await ot.resolve_active_plan_id("sess-a") == "execution_plan_main"


@pytest.mark.anyio
async def test_mark_task_completed_uses_active_plan_when_plan_id_empty(monkeypatch):
    captured: dict = {}

    async def fake_resolve(session_id):
        return "execution_plan_active"

    async def fake_fetch_session(plan_id):
        return "sess-1"

    async def fake_fetch_record(plan_id):
        return {
            "approved_markdown": (
                "## Tasks\n- [ ] `task_01` **Do thing** (profile: -) (deps: none)\n"
            ),
            "draft_markdown": None,
            "revision": 1,
        }

    async def fake_update(plan_id, **kwargs):
        captured["plan_id"] = plan_id

    monkeypatch.setattr(ot, "resolve_active_plan_id", fake_resolve)
    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_session", fake_fetch_session)
    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_record", fake_fetch_record)
    monkeypatch.setattr("src.runtime.orchestration_db.update_plan_after_wait", fake_update)
    monkeypatch.setattr(ot.tool_event_bus, "put_event", lambda *_a, **_k: None)
    monkeypatch.setattr("src.runtime.redis_client.redis_enqueue_session_event", lambda *_a, **_k: None)

    out = await ot.run_mark_task_completed(
        "",
        "task_01",
        session_id="sess-1",
        user_id="u1",
    )
    assert captured["plan_id"] == "execution_plan_active"
    assert "task_01" in out


@pytest.mark.anyio
async def test_list_session_execution_plans_empty(monkeypatch):
    async def fake_list(session_id, *, limit=20):
        return []

    monkeypatch.setattr("src.runtime.orchestration_db.list_plans_for_session", fake_list)
    out = await ot.run_list_session_execution_plans(session_id="sess-x", user_id="u1")
    assert "No orchestration plan" in out
    assert "execution_plan_*.md" in out

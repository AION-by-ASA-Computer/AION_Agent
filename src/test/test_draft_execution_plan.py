"""draft_execution_plan built-in orchestration tool."""

import asyncio

import pytest

from src.runtime import orchestration_tools as ot


@pytest.mark.anyio
async def test_run_draft_execution_plan_registers_pending(monkeypatch):
    captured: dict = {}

    async def fake_setup(md, *, plan_id, session_id, user_id):
        captured["plan_id"] = plan_id
        captured["markdown"] = md
        captured["session_id"] = session_id

    async def fake_insert(*args, **kwargs):
        return None

    monkeypatch.setattr(ot, "setup_execution_plan_from_markdown", fake_setup)
    monkeypatch.setattr(
        "src.runtime.plan_coercion.new_execution_plan_id",
        lambda: "execution_plan_test01",
    )

    from src.runtime import orchestration_db as odb

    monkeypatch.setattr(odb, "insert_execution_plan", fake_insert)

    async def _noop_redis(*_a, **_k):
        return None

    monkeypatch.setattr(
        "src.runtime.redis_client.redis_enqueue_session_event",
        _noop_redis,
    )

    msg = await ot.run_draft_execution_plan(
        "Build a course",
        [
            {"id": "task_01", "title": "Outline", "depends_on": []},
            {"id": "task_02", "title": "Draft chapter 1", "depends_on": ["task_01"]},
        ],
        session_id="sess-1",
        user_id="u1",
    )

    assert "execution_plan_test01" in msg
    assert captured["plan_id"] == "execution_plan_test01"
    assert "## Goal" in captured["markdown"]
    assert "task_01" in captured["markdown"]


@pytest.mark.anyio
async def test_run_draft_execution_plan_reuses_turn_plan_id(monkeypatch):
    captured: dict = {}

    async def fake_setup(md, *, plan_id, session_id, user_id):
        captured["plan_id"] = plan_id

    monkeypatch.setattr(ot, "setup_execution_plan_from_markdown", fake_setup)
    async def _noop_redis(*_a, **_k):
        return None

    monkeypatch.setattr(
        "src.runtime.redis_client.redis_enqueue_session_event",
        _noop_redis,
    )

    from src.runtime.context import clear_context, set_context

    set_context("sess-1", None, None, None, turn_plan_id="execution_plan_turn99")
    try:
        await ot.run_draft_execution_plan(
            "Goal",
            [
                {"id": "task_01", "title": "Step one", "depends_on": []},
                {"id": "task_02", "title": "Step two", "depends_on": ["task_01"]},
            ],
            session_id="sess-1",
            user_id="u1",
        )
    finally:
        clear_context()

    assert captured["plan_id"] == "execution_plan_turn99"


@pytest.mark.anyio
async def test_run_draft_execution_plan_requires_tasks():
    with pytest.raises(ValueError, match="tasks is required"):
        await ot.run_draft_execution_plan(
            "Goal only",
            None,
            session_id="sess-1",
            user_id="u1",
        )

"""Plan wait registry: rehydrate pending state from DB when Redis is empty."""

import json
import uuid

import pytest

from src.a2a.protocol import ExecutionPlan
from src.runtime.plan_wait_registry import (
    rehydrate_plan_pending,
    resolve_plan,
    set_pending,
)


@pytest.mark.anyio
async def test_resolve_plan_rehydrates_from_db(monkeypatch):
    plan_id = uuid.uuid4().hex
    session_id = "thread-rehydrate-01"
    plan = ExecutionPlan.from_goal_and_tasks(
        "Test goal for rehydrate",
        [
            {"id": "task_01", "title": "First", "description": "Do first thing", "depends_on": []},
            {"id": "task_02", "title": "Second", "description": "Do second thing", "depends_on": ["task_01"]},
        ],
    )
    plan_dict = json.loads(plan.model_dump_json())
    draft_md = "# Execution Plan\n\n## Goal\nTest\n\n## Tasks\n- [ ] `task_01` **First**"

    async def _fake_bundle(pid: str):
        assert pid == plan_id
        return {
            "session_id": session_id,
            "user_id": "user-1",
            "status": "draft_pending",
            "plan_markdown": draft_md,
            "plan": plan_dict,
            "todos": [],
            "annotations": {},
            "revision": 1,
        }

    monkeypatch.setattr(
        "src.runtime.orchestration_db.fetch_plan_sse_bundle",
        _fake_bundle,
    )

    res = await resolve_plan(
        plan_id,
        session_id=session_id,
        approved=True,
        approved_plan=None,
    )
    assert res.get("ok") is True
    assert res.get("state") == "approved"


@pytest.mark.anyio
async def test_rehydrate_plan_pending_skips_wrong_session(monkeypatch):
    plan_id = uuid.uuid4().hex

    async def _fake_bundle(_pid: str):
        return {
            "session_id": "other-session",
            "user_id": "u1",
            "status": "draft_pending",
            "plan_markdown": "# Plan",
            "plan": {},
            "todos": [],
            "annotations": {},
            "revision": 1,
        }

    monkeypatch.setattr(
        "src.runtime.orchestration_db.fetch_plan_sse_bundle",
        _fake_bundle,
    )
    ok = await rehydrate_plan_pending(plan_id, session_id="expected-session")
    assert ok is False


@pytest.mark.anyio
async def test_set_pending_then_resolve_without_rehydrate():
    plan_id = uuid.uuid4().hex
    session_id = "thread-direct-01"
    draft = {"plan_markdown": "# Plan", "plan_json": {}, "todos": [], "annotations": {}, "revision": 1}
    ok = await set_pending(
        plan_id,
        session_id=session_id,
        user_id="u1",
        draft=draft,
        ttl_sec=120,
    )
    assert ok is True
    res = await resolve_plan(
        plan_id,
        session_id=session_id,
        approved=True,
        approved_plan=draft,
    )
    assert res.get("ok") is True

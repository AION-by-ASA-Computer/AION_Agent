import asyncio
import json
import uuid

from src.a2a.protocol import ExecutionPlan
from src.runtime.plan_wait_registry import resolve_plan, set_pending, wait_for_resolution


def test_plan_wait_registry_approve():
    async def _run():
        plan_id = uuid.uuid4().hex
        session_id = "thread-orch-wait-01"
        plan = ExecutionPlan.from_goal_and_tasks(
            "test", [{"title": "step", "description": "d", "depends_on": []}]
        )
        draft = json.loads(plan.model_dump_json())

        ok = await set_pending(plan_id, session_id=session_id, user_id="u1", draft=draft, ttl_sec=120)
        assert ok is True

        async def _approve():
            await asyncio.sleep(0.12)
            await resolve_plan(plan_id, session_id=session_id, approved=True, approved_plan=None)

        done, _ = await asyncio.gather(
            wait_for_resolution(plan_id, poll_sec=0.05, timeout_sec=3.0),
            _approve(),
        )
        assert done.get("state") == "approved"
        assert done.get("plan") is not None

    asyncio.run(_run())

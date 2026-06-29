import asyncio

from src.runtime import orchestration_tools as ot


def test_setup_execution_plan_casts_ttl_to_int(monkeypatch):
    captured = {}

    async def fake_set_pending(plan_id, *, session_id, user_id, draft, ttl_sec):
        captured["ttl_sec"] = ttl_sec

    async def fake_upsert_execution_plan_draft(*args, **kwargs):
        return True

    monkeypatch.setattr(ot, "set_pending", fake_set_pending)
    monkeypatch.setattr(ot.tool_event_bus, "put_event", lambda *args, **kwargs: None)
    monkeypatch.setenv("AION_ORCH_PLAN_WAIT_TIMEOUT_SEC", "600.9")

    from src.runtime import orchestration_db as odb

    monkeypatch.setattr(
        odb, "upsert_execution_plan_draft", fake_upsert_execution_plan_draft
    )

    ok = asyncio.run(
        ot.setup_execution_plan_from_markdown(
            "<plan>\n# Plan\n## Goal\nG\n## Tasks\n- [ ] `t1` **Task** (profile: p) (deps: none)\n  - Description: d1\n</plan>",
            plan_id="p1",
            session_id="s1",
            user_id="u1",
        )
    )

    assert ok is True
    assert isinstance(captured["ttl_sec"], int)
    assert captured["ttl_sec"] >= 1

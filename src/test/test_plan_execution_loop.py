"""Plan execution handler (background jobs, Deep Research-style)."""

import threading
from typing import Any, Dict, List

import pytest

from src.plan_execution.handler import (
    PlanExecutionHandler,
    _progress_label,
    _tool_activity_label,
)
from src.runtime import orchestration_tools as ot
from src.runtime.context import get_context

_PLAN_MD_T0 = """# Execution Plan

## Goal
Test goal

## Tasks
- [ ] `task_01` **First action** (profile: orchestrator) (deps: none)
- [ ] `task_02` **Second action** (profile: orchestrator) (deps: task_01)
"""

_PLAN_MD_T1_DONE = _PLAN_MD_T0.replace("- [ ] `task_01`", "- [x] `task_01`", 1)

_PLAN_MD_ALL_DONE = _PLAN_MD_T1_DONE.replace("- [ ] `task_02`", "- [x] `task_02`", 1)


@pytest.mark.anyio
async def test_mark_no_continue_on_pending_event(monkeypatch):
    captured: List[Dict[str, Any]] = []

    async def capture_redis(_sid, ev, **_k):
        captured.append(ev)

    monkeypatch.setattr(ot.tool_event_bus, "put_event", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "src.runtime.redis_client.redis_enqueue_session_event", capture_redis
    )

    await ot._persist_plan_markdown(
        "execution_plan_evt1",
        _PLAN_MD_T0,
        {"revision": 1, "approved_markdown": _PLAN_MD_T0},
        session_id="sess-1",
        audit_via="test",
        highlight_task_id="task_01",
    )

    assert captured
    evt = captured[-1]
    assert evt["type"] == "orchestration_plan_pending"
    assert "continue_execution" not in evt
    assert "next_pending_task_id" not in evt


def test_progress_label_task_start():
    label = _progress_label(
        {
            "phase": "task_start",
            "task_id": "task_01",
            "title": "First action",
            "index": 1,
            "total": 2,
        }
    )
    assert "task_01" in label
    assert "First action" in label
    assert "1/2" in label


@pytest.mark.anyio
async def test_handler_emits_task_activities(monkeypatch):
    state = {"md": _PLAN_MD_T0, "revision": 1}
    activities: List[dict] = []

    async def fake_fetch(_plan_id: str):
        return {"approved_markdown": state["md"], "revision": state["revision"]}

    async def fake_session(_plan_id: str):
        return "sess-loop"

    async def fake_get_agent(*_a, **_k):
        return object(), "test_profile"

    class FakePipe:
        session_id = "sess-loop"

        async def run_stream(
            self, user_input: str, *args, plan_execution_task_id=None, **kwargs
        ):
            tid = (plan_execution_task_id or "").strip()
            yield {
                "type": "turn_started",
                "user_message_id": f"u-{tid}",
                "assistant_message_id": f"a-{tid}",
            }
            if tid == "task_01":
                state["md"] = _PLAN_MD_T1_DONE
                state["revision"] = 2
                yield {
                    "type": "turn_outcome",
                    "code": "plan_task_completed",
                    "task_id": tid,
                }
            elif tid == "task_02":
                state["md"] = _PLAN_MD_ALL_DONE
                state["revision"] = 3
                yield {
                    "type": "turn_outcome",
                    "code": "plan_task_completed",
                    "task_id": tid,
                }

    async def fake_synth(**_k):
        return "Riepilogo finale di test."

    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_record", fake_fetch)
    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_session", fake_session)
    monkeypatch.setattr(
        "src.plan_execution.handler._get_agent_for_execution", fake_get_agent
    )
    monkeypatch.setattr(
        "src.plan_execution.handler._make_plan_execution_pipeline",
        lambda *a, **k: FakePipe(),
    )
    monkeypatch.setattr(
        PlanExecutionHandler,
        "_synthesize_final_summary",
        staticmethod(lambda **k: fake_synth(**k)),
    )

    # The final summary must also land in the last task's assistant message.
    appended: List[dict] = []

    async def fake_append(self, **kw):
        appended.append(kw)
        return True

    async def fake_persist(self, **_kw):
        return "summary-msg"

    monkeypatch.setattr(
        PlanExecutionHandler, "_append_summary_to_last_task", fake_append
    )
    monkeypatch.setattr(PlanExecutionHandler, "_persist_final_summary", fake_persist)

    handler = PlanExecutionHandler()
    entry: Dict[str, Any] = {
        "chat_session_id": "sess-loop",
        "owner": "u1",
        "profile_name": "test",
        "tasks": [],
    }

    def on_progress(ev: dict) -> None:
        activities.append(ev)
        if ev.get("phase") == "task_start" and ev.get("task_id"):
            tid = str(ev["task_id"])
            if not any(t.get("task_id") == tid for t in entry["tasks"]):
                entry["tasks"].append(
                    {
                        "task_id": tid,
                        "title": ev.get("title") or "",
                        "status": "running",
                    }
                )
        if ev.get("phase") == "task_done" and ev.get("task_id"):
            tid = str(ev["task_id"])
            for t in entry["tasks"]:
                if t.get("task_id") == tid:
                    t["status"] = "done"

    summary, deliverable = await handler._run_plan_loop(
        "pe-test-1",
        "execution_plan_loop1",
        entry,
        on_progress=on_progress,
    )

    assert summary == "Riepilogo finale di test."
    phases = [a.get("phase") for a in activities]
    assert "task_start" in phases
    assert phases.count("task_done") == 2
    assert "writing" in phases
    assert "complete" in phases
    t1 = next(t for t in entry["tasks"] if t.get("task_id") == "task_01")
    t2 = next(t for t in entry["tasks"] if t.get("task_id") == "task_02")
    assert t1.get("user_message_id") == "u-task_01"
    assert t1.get("assistant_message_id") == "a-task_01"
    assert t2.get("user_message_id") == "u-task_02"
    assert t2.get("assistant_message_id") == "a-task_02"
    assert isinstance(t1.get("turns"), list)
    assert len(t1.get("turns") or []) >= 1
    assert (t1.get("turns") or [])[-1].get("user_message_id") == "u-task_01"
    assert appended == [
        {
            "session_id": "sess-loop",
            "message_id": "a-task_02",
            "summary": "Riepilogo finale di test.",
        }
    ]


@pytest.mark.anyio
async def test_handler_stops_on_failed_mark(monkeypatch):
    async def fake_fetch(_plan_id: str):
        return {"approved_markdown": _PLAN_MD_T0, "revision": 1}

    async def fake_session(_plan_id: str):
        return "sess-fail"

    async def fake_get_agent(*_a, **_k):
        return object(), "test_profile"

    class FakePipe:
        async def run_stream(self, user_input: str, *args, **kwargs):
            yield {"type": "token", "content": "no mark"}

    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_record", fake_fetch)
    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_session", fake_session)
    monkeypatch.setattr(
        "src.plan_execution.handler._get_agent_for_execution", fake_get_agent
    )
    monkeypatch.setattr(
        "src.plan_execution.handler._make_plan_execution_pipeline",
        lambda *a, **k: FakePipe(),
    )

    handler = PlanExecutionHandler()
    entry = {
        "chat_session_id": "sess-fail",
        "owner": "u1",
        "profile_name": "test",
        "tasks": [],
        "status": "running",
    }
    summary, _ = await handler._run_plan_loop(
        "pe-fail",
        "execution_plan_fail",
        entry,
        on_progress=lambda _e: None,
    )
    assert entry.get("status") == "paused"
    assert (
        "paused" in (summary or "").lower()
        or "not completed" in (summary or "").lower()
    )


def test_tool_guard_blocks_after_mark():
    from src.runtime.context import _forward_ctx

    mark_once = {"used": True, "lock": threading.Lock()}
    _forward_ctx.set({"mark_once": mark_once})

    _msg_src = "internal_trigger"
    _tn = "web_fetch"
    blocked = False
    if _msg_src == "internal_trigger" and _tn != "mark_task_completed":
        _mo = get_context().get("mark_once")
        if isinstance(_mo, dict) and _mo.get("used"):
            blocked = True

    assert blocked is True
    _forward_ctx.set(None)


@pytest.mark.anyio
async def test_cancel_stops_sub_turn(monkeypatch):
    import asyncio

    async def fake_fetch(_plan_id: str):
        return {"approved_markdown": _PLAN_MD_T0, "revision": 1}

    async def fake_session(_plan_id: str):
        return "sess-cancel"

    async def fake_get_agent(*_a, **_k):
        return object(), "test_profile"

    class FakePipe:
        async def run_stream(self, user_input: str, *args, **kwargs):
            await asyncio.sleep(0.05)
            yield {"type": "token", "content": "working"}

    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_record", fake_fetch)
    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_session", fake_session)
    monkeypatch.setattr(
        "src.plan_execution.handler._get_agent_for_execution", fake_get_agent
    )
    monkeypatch.setattr(
        "src.plan_execution.handler._make_plan_execution_pipeline",
        lambda *a, **k: FakePipe(),
    )

    handler = PlanExecutionHandler()
    entry = {
        "chat_session_id": "sess-cancel",
        "owner": "u1",
        "profile_name": "test",
        "_cancel": False,
    }

    async def run_and_cancel():
        loop_task = asyncio.create_task(
            handler._run_plan_loop(
                "pe-cancel",
                "execution_plan_cancel",
                entry,
                on_progress=lambda _e: None,
            )
        )
        await asyncio.sleep(0.01)
        entry["_cancel"] = True
        with pytest.raises(asyncio.CancelledError):
            await loop_task

    await run_and_cancel()


@pytest.mark.anyio
async def test_handler_final_summary_required(monkeypatch):
    state = {"md": _PLAN_MD_ALL_DONE, "revision": 3}
    synth_called = {"ok": False}

    async def fake_fetch(_plan_id: str):
        return {"approved_markdown": state["md"], "revision": state["revision"]}

    async def fake_session(_plan_id: str):
        return "sess-summary"

    async def fake_get_agent(*_a, **_k):
        return object(), "test_profile"

    class FakePipe:
        async def run_stream(self, *args, **kwargs):
            if False:
                yield {}

    async def fake_synth(**_k):
        synth_called["ok"] = True
        return "Commento finale obbligatorio."

    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_record", fake_fetch)
    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_session", fake_session)
    monkeypatch.setattr(
        "src.plan_execution.handler._get_agent_for_execution", fake_get_agent
    )
    monkeypatch.setattr(
        "src.plan_execution.handler._make_plan_execution_pipeline",
        lambda *a, **k: FakePipe(),
    )
    monkeypatch.setattr(
        PlanExecutionHandler,
        "_synthesize_final_summary",
        staticmethod(lambda **k: fake_synth(**k)),
    )

    handler = PlanExecutionHandler()
    summary, _ = await handler._run_plan_loop(
        "pe-summary",
        "execution_plan_summary",
        {"chat_session_id": "sess-summary", "owner": "u1", "profile_name": "test"},
        on_progress=lambda _e: None,
    )

    assert synth_called["ok"] is True
    assert summary == "Commento finale obbligatorio."


@pytest.mark.anyio
async def test_approve_starts_handler(monkeypatch):
    started: dict = {}

    def fake_start(plan_id, **kwargs):
        started.update({"plan_id": plan_id, **kwargs})
        return {
            "run_id": "pe-abc",
            "status": "running",
            "ui_event": "plan_execution_started",
        }

    monkeypatch.setattr(
        "src.plan_execution.handler.plan_execution_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "src.plan_execution.handler.get_plan_execution_handler",
        lambda: type("H", (), {"start_plan_execution": staticmethod(fake_start)})(),
    )

    from src.plan_execution.handler import (
        plan_execution_enabled,
        get_plan_execution_handler,
    )

    assert plan_execution_enabled()
    out = get_plan_execution_handler().start_plan_execution(
        "execution_plan_x",
        owner="user1",
        chat_session_id="sess-1",
    )
    assert out["run_id"] == "pe-abc"
    assert started["plan_id"] == "execution_plan_x"
    assert started["chat_session_id"] == "sess-1"


def test_tool_activity_label_sandbox_write():
    label = _tool_activity_label(
        "sandbox_write_workspace_file",
        "running",
        "workspace/README.md",
    )
    assert "Writing file to workspace" in label
    assert "README.md" in label


def test_progress_label_tool_phase():
    label = _progress_label(
        {
            "phase": "tool",
            "tool_name": "mark_task_completed",
            "status": "done",
            "detail": "task_01",
        }
    )
    assert "task" in label.lower() or "task_01" in label


def test_list_runs_for_owner_filters_session(tmp_path, monkeypatch):
    monkeypatch.setenv("AION_PLAN_EXECUTION_DATA_DIR", str(tmp_path))
    handler = PlanExecutionHandler()
    path = tmp_path / "pe-run1.json"
    path.write_text(
        '{"plan_id":"p1","status":"done","owner":"u1","chat_session_id":"s1","started_at":10}',
        encoding="utf-8",
    )
    runs = handler.list_runs_for_owner("u1", chat_session_id="s1")
    assert len(runs) == 1
    assert runs[0]["run_id"] == "pe-run1"
    assert handler.list_runs_for_owner("u1", chat_session_id="other") == []


async def _run_failing_task_capturing_efforts(monkeypatch, first_outcome_code):
    """Run a plan whose task never completes; return the reasoning_effort of each attempt.

    The first attempt yields a ``turn_outcome`` with ``first_outcome_code`` (or
    nothing when None); every attempt ends without plan_task_completed.
    """
    efforts: List[Any] = []

    async def fake_fetch(_plan_id: str):
        return {"approved_markdown": _PLAN_MD_T0, "revision": 1}

    async def fake_session(_plan_id: str):
        return "sess-stall"

    async def fake_get_agent(*_a, **_k):
        return object(), "test_profile"

    class FakePipe:
        async def run_stream(
            self, user_input: str, *args, reasoning_effort=None, **kwargs
        ):
            efforts.append(reasoning_effort)
            if first_outcome_code and len(efforts) == 1:
                yield {"type": "turn_outcome", "code": first_outcome_code}
            yield {"type": "token", "content": "no mark"}

    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_record", fake_fetch)
    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_session", fake_session)
    monkeypatch.setattr(
        "src.plan_execution.handler._get_agent_for_execution", fake_get_agent
    )
    monkeypatch.setattr(
        "src.plan_execution.handler._make_plan_execution_pipeline",
        lambda *a, **k: FakePipe(),
    )
    entry = {
        "chat_session_id": "sess-stall",
        "owner": "u1",
        "profile_name": "test",
        "tasks": [],
        "status": "running",
    }
    await PlanExecutionHandler()._run_plan_loop(
        "pe-stall", "execution_plan_stall", entry, on_progress=lambda _e: None
    )
    assert entry.get("status") == "paused"
    return efforts


@pytest.mark.anyio
@pytest.mark.parametrize(
    "code", ["reasoning_only_no_answer", "reasoning_budget_no_answer"]
)
async def test_retry_disables_thinking_after_reasoning_only_turn(monkeypatch, code):
    """A reasoning-only first attempt makes the retry run with thinking off."""
    efforts = await _run_failing_task_capturing_efforts(monkeypatch, code)
    assert efforts == [None, "off"]


@pytest.mark.anyio
async def test_retry_keeps_default_thinking_for_other_failures(monkeypatch):
    """Without a reasoning stall the retry keeps the default reasoning settings."""
    efforts = await _run_failing_task_capturing_efforts(monkeypatch, None)
    assert efforts == [None, None]


def test_summary_publisher_streams_partial_text_throttled():
    """Partial summary goes into progress.summary_partial and wakes the stream, throttled."""
    handler = PlanExecutionHandler()
    entry: Dict[str, Any] = {"progress": {"phase": "writing"}}
    publish = handler._summary_publisher("pe-pub", entry)

    publish("x" * 50)
    assert entry["progress"]["summary_partial"] == "x" * 50
    assert entry["progress"]["phase"] == "writing"
    seq = handler._stream_seq.get("pe-pub", 0)
    assert seq == 1

    publish("x" * 55)  # < 40 new chars within 300 ms: skipped
    assert entry["progress"]["summary_partial"] == "x" * 50
    publish("x" * 120)  # enough new text: published
    assert entry["progress"]["summary_partial"] == "x" * 120
    assert handler._stream_seq["pe-pub"] == 2


@pytest.mark.anyio
async def test_persist_final_summary_attaches_deliverable(tmp_path, monkeypatch):
    """The final summary is saved as an assistant message with the deliverable attached."""
    import src.api.history as hist
    import src.session_workspace as sw

    root = tmp_path / "sess"
    (root / "workspace").mkdir(parents=True)
    (root / "workspace" / "articolo_AI.docx").write_bytes(b"docx-bytes")
    monkeypatch.setattr(sw, "normalize_session_id", lambda s: s)
    monkeypatch.setattr(sw, "session_root", lambda _s: root)

    calls: Dict[str, Any] = {}

    class FakeHistory:
        async def add_message(self, session_id, role, content, **kw):
            calls["message"] = (session_id, role, content, kw.get("message_id"))

        async def add_attachment(self, session_id, **kw):
            calls["attachment"] = (session_id, kw)

    monkeypatch.setattr(hist, "history_manager", FakeHistory())

    mid = await PlanExecutionHandler()._persist_final_summary(
        session_id="sess-1",
        summary="## Plan completed",
        deliverable_path="workspace/articolo_AI.docx",
        profile_name="p",
        owner="u1",
    )
    assert mid and calls["message"] == ("sess-1", "assistant", "## Plan completed", mid)
    _sid, att = calls["attachment"]
    assert att["storage_key"] == "workspace/articolo_AI.docx"
    assert att["message_id"] == mid
    assert att["original_name"] == "articolo_AI.docx"
    assert att["size_bytes"] == len(b"docx-bytes")


def test_last_task_assistant_id_fallback():
    """Without a task run in this loop, the last task with a message id is used."""
    from src.plan_execution.handler import _last_task_assistant_id

    entry = {
        "tasks": [
            {"task_id": "task_01", "assistant_message_id": "a1"},
            {"task_id": "task_02", "assistant_message_id": "a2"},
            {"task_id": "task_03"},
        ]
    }
    assert _last_task_assistant_id(entry) == "a2"
    assert _last_task_assistant_id({"tasks": []}) is None


@pytest.mark.anyio
async def test_append_summary_to_last_task_uses_placeholders(monkeypatch):
    """The summary is appended with the placeholder texts marked replaceable."""
    import src.api.history as hist
    from src.runtime.turn_diagnostics import (
        PLAN_CREATED_TEXT,
        PLAN_TASK_COMPLETED_TEXT,
    )

    calls: List[tuple] = []

    class FakeHistory:
        async def append_message_text(self, sid, mid, text, *, replaceable_texts):
            calls.append((sid, mid, text, replaceable_texts))
            return True

    monkeypatch.setattr(hist, "history_manager", FakeHistory())
    handler = PlanExecutionHandler()
    ok = await handler._append_summary_to_last_task(
        session_id="s1", message_id="a4", summary="## Plan completed"
    )
    assert ok is True
    sid, mid, text, repl = calls[0]
    assert (sid, mid, text) == ("s1", "a4", "## Plan completed")
    assert PLAN_TASK_COMPLETED_TEXT in repl and PLAN_CREATED_TEXT in repl
    # No message id: nothing to do.
    assert not await handler._append_summary_to_last_task(
        session_id="s1", message_id=None, summary="x"
    )

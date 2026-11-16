"""Plan-closing tool ``complete_execution_plan`` and the closing turn.

After the last ``mark_task_completed`` the plan execution handler runs one more
agent turn in which the agent calls ``complete_execution_plan``: the plan is
closed, the summary becomes the chat answer and every generated document is
rendered as a file card (and persisted as an attachment). These tests cover the
tool, the stream-loop rendering, the handler's closing turn and its fallback.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.plan_execution.handler import PlanExecutionHandler
from src.runtime import orchestration_tools as ot
from src.runtime.plan_execution import (
    build_plan_completion_reminder,
    build_plan_completion_trigger,
)
from src.runtime.stream.loop import StreamLoop, _BreakSignal
from src.runtime.timeline_builder import TimelineBuilder
from src.test.test_mark_task_completed_tool_end import _FakeTurnPersist, _guards

_PLAN_ALL_DONE = """# Execution Plan

## Goal
Write an article about AI discoveries and deliver it as a Word file.

## Deliverable
`workspace/articolo.docx`

## Tasks
- [x] `task_01` **Research** (deps: none)
- [x] `task_02` **Write docx** (deps: task_01)
"""

_PLAN_PENDING = _PLAN_ALL_DONE.replace("- [x] `task_02`", "- [ ] `task_02`")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Session folder in tmp_path with a typical plan output."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "articolo.docx").write_bytes(b"PK\x03\x04docx")
    (ws / "articolo.md").write_text("# Articolo", encoding="utf-8")
    (ws / "create_doc.js").write_text("// helper", encoding="utf-8")
    (ws / "data.json").write_text("{}", encoding="utf-8")
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "readme.md").write_text("dep", encoding="utf-8")
    monkeypatch.setattr("src.session_workspace.normalize_session_id", lambda s: s)
    monkeypatch.setattr("src.session_workspace.session_root", lambda _s: tmp_path)
    return tmp_path


def _patch_plan_db(monkeypatch, markdown: str, audits: List[tuple]):
    async def fake_session(_pid):
        return "sess-close"

    async def fake_record(_pid):
        return {"approved_markdown": markdown, "revision": 3}

    async def fake_audit(*args, **_kw):
        audits.append(args)

    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_session", fake_session)
    monkeypatch.setattr("src.runtime.orchestration_db.fetch_plan_record", fake_record)
    monkeypatch.setattr("src.runtime.orchestration_db.insert_audit", fake_audit)


# --- deliverable detection ---------------------------------------------------


def test_collect_deliverables_auto_skips_scripts_and_dependencies(workspace):
    """Fallback detection: main deliverable first, only document formats."""
    files = ot.collect_plan_deliverables("sess-close", plan_markdown=_PLAN_ALL_DONE)
    paths = [f["path"] for f in files]
    assert paths[0] == "workspace/articolo.docx"
    assert "workspace/articolo.md" in paths
    assert "workspace/create_doc.js" not in paths
    assert "workspace/data.json" not in paths
    assert not any("node_modules" in p for p in paths)
    docx = files[0]
    assert docx["name"] == "articolo.docx"
    assert docx["size_bytes"] > 0
    assert "wordprocessingml" in docx["mime"]


def test_collect_deliverables_requested_paths_are_validated(workspace):
    """Agent-listed paths win; missing files and escapes are dropped."""
    files = ot.collect_plan_deliverables(
        "sess-close",
        [
            "articolo.docx",
            "workspace/data.json",
            "workspace/missing.pdf",
            "../secret.txt",
        ],
    )
    assert [f["path"] for f in files] == [
        "workspace/articolo.docx",
        "workspace/data.json",
    ]


# --- tool --------------------------------------------------------------------


@pytest.mark.anyio
async def test_complete_plan_returns_summary_and_documents(workspace, monkeypatch):
    """All tasks done: JSON payload with summary + deliverables, audit written."""
    audits: List[tuple] = []
    _patch_plan_db(monkeypatch, _PLAN_ALL_DONE, audits)

    out = await ot.run_complete_execution_plan(
        "execution_plan_close",
        "Articolo completato.",
        ["workspace/articolo.docx"],
        session_id="sess-close",
        user_id="u1",
    )
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["plan_id"] == "execution_plan_close"
    assert payload["summary"] == "Articolo completato."
    assert [f["path"] for f in payload["deliverables"]] == ["workspace/articolo.docx"]
    assert audits and audits[0][3] == "plan_completed"


@pytest.mark.anyio
async def test_complete_plan_refuses_with_pending_tasks(workspace, monkeypatch):
    """Closing while a task is pending must fail (tool_error for the agent)."""
    _patch_plan_db(monkeypatch, _PLAN_PENDING, [])
    with pytest.raises(ValueError, match="pending"):
        await ot.run_complete_execution_plan(
            "execution_plan_close",
            "Done.",
            None,
            session_id="sess-close",
            user_id="u1",
        )


@pytest.mark.anyio
async def test_complete_plan_accepts_deliverables_as_json_string(
    workspace, monkeypatch
):
    """Some models send the array as a JSON string."""
    _patch_plan_db(monkeypatch, _PLAN_ALL_DONE, [])
    out = await ot.run_complete_execution_plan(
        "execution_plan_close",
        "Done.",
        '["workspace/articolo.md"]',
        session_id="sess-close",
        user_id="u1",
    )
    assert [f["path"] for f in json.loads(out)["deliverables"]] == [
        "workspace/articolo.md"
    ]


def test_complete_plan_is_builtin_and_blocked_in_plan_mode():
    """Registered with the orchestration tools, not usable while drafting."""
    from src.runtime.plan_mode import DEFAULT_PLAN_MODE_BLOCKED_TOOLS

    assert ot.COMPLETE_PLAN_TOOL_NAME in ot.ORCHESTRATION_BUILTIN_TOOL_NAMES
    assert ot.COMPLETE_PLAN_TOOL_NAME in DEFAULT_PLAN_MODE_BLOCKED_TOOLS


def test_completion_prompts_ask_for_the_tool():
    """Closing reminder/trigger point the agent to complete_execution_plan."""
    rem = build_plan_completion_reminder(
        plan_id="execution_plan_close",
        plan_markdown=_PLAN_ALL_DONE,
        deliverables=["workspace/articolo.docx"],
    )
    assert "complete_execution_plan" in rem
    assert "workspace/articolo.docx" in rem
    assert "mark_task_completed" in rem  # told NOT to call it
    assert "complete_execution_plan" in build_plan_completion_trigger(
        "execution_plan_close"
    )


# --- stream loop ---------------------------------------------------------------


def _loop_with_timeline():
    persist = _FakeTurnPersist()
    persist.attachments = []
    persist.queue_attachment = lambda **kw: persist.attachments.append(kw)
    timeline = TimelineBuilder()

    def track(out):
        timeline.apply_chunk(out)
        return out

    sl = StreamLoop(
        queue=asyncio.Queue(),
        stop_event=SimpleNamespace(set=lambda: None, is_set=lambda: False),
        loop=asyncio.get_running_loop(),
        turn_guards=_guards(),
        artifact_parser=None,
        artifact_manager=None,
        turn_persist=persist,
        session_id="sess-close",
        profile_name="aion_std",
        user_id="u1",
        assistant_message_id="asst-close",
        message_source="internal_trigger",
        track_sse=track,
        timeline_builder=timeline,
    )
    return sl, persist, timeline


def _tool_event(kind: str, output: str = "") -> Dict[str, Any]:
    evt: Dict[str, Any] = {
        "type": kind,
        "id": "call_close_1",
        "name": "complete_execution_plan",
        "input": {"summary": "x"},
    }
    if kind == "tool_end":
        evt["output"] = output
    return {"type": "tool_event", "event": evt}


@pytest.mark.anyio
async def test_stream_loop_renders_summary_and_document_cards():
    """tool_end → summary text, one saved artifact per document, plan_completed."""
    sl, persist, timeline = _loop_with_timeline()
    payload = {
        "ok": True,
        "plan_id": "execution_plan_close",
        "summary": "Articolo pronto.",
        "deliverables": [
            {
                "path": "workspace/articolo.docx",
                "name": "articolo.docx",
                "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "size_bytes": 10,
            },
            {
                "path": "workspace/articolo.md",
                "name": "articolo.md",
                "mime": "text/markdown",
                "size_bytes": 3,
            },
        ],
    }
    [e async for e in sl._handle_tool_event(_tool_event("tool_start"))]
    out = [
        e
        async for e in sl._handle_tool_event(
            _tool_event("tool_end", json.dumps(payload))
        )
    ]

    # Summary is the turn's answer (persisted via full_response).
    assert "".join(sl.full_response) == "Articolo pronto."
    # One saved artifact (file card) per document, attached to the message.
    ends = [e for e in out if isinstance(e, dict) and e.get("type") == "artifact_end"]
    assert [e["artifact"]["path"] for e in ends] == [
        "workspace/articolo.docx",
        "workspace/articolo.md",
    ]
    assert [a["storage_key"] for a in persist.attachments] == [
        "workspace/articolo.docx",
        "workspace/articolo.md",
    ]
    arts = [s for s in timeline.segments if s.get("kind") == "artifact"]
    assert {s.get("savedPath") for s in arts} == {
        "workspace/articolo.docx",
        "workspace/articolo.md",
    }
    # Tool card closed, outcome for the handler, then the turn stops.
    tools = [s for s in timeline.segments if s.get("kind") == "tool"]
    assert tools and all(s.get("status") != "running" for s in tools)
    outcome = next(
        e for e in out if isinstance(e, dict) and e.get("type") == "turn_outcome"
    )
    assert outcome["code"] == "plan_completed"
    assert "message" not in outcome  # nothing rendered as a banner
    assert outcome["details"]["assistant_message_id"] == "asst-close"
    assert outcome["details"]["deliverables"][0] == "workspace/articolo.docx"
    assert isinstance(out[-1], _BreakSignal)
    assert sl.stop_reason == "plan_completed"


@pytest.mark.anyio
async def test_stream_loop_keeps_agent_text_when_already_written():
    """If the agent wrote its own answer, the summary is not appended twice."""
    sl, _persist, _timeline = _loop_with_timeline()
    sl.full_response.append("Testo dell'agente.")
    payload = {"ok": True, "plan_id": "p", "summary": "Riepilogo.", "deliverables": []}
    [e async for e in sl._handle_tool_event(_tool_event("tool_start"))]
    [
        e
        async for e in sl._handle_tool_event(
            _tool_event("tool_end", json.dumps(payload))
        )
    ]
    assert "".join(sl.full_response) == "Testo dell'agente."


@pytest.mark.anyio
async def test_mark_task_completed_outcome_has_no_banner():
    """The 'Turn interrupted — the server will continue…' banner is gone."""
    sl, _persist, timeline = _loop_with_timeline()
    start = {
        "type": "tool_event",
        "event": {
            "type": "tool_start",
            "id": "c2",
            "name": "mark_task_completed",
            "input": {},
        },
    }
    end = {
        "type": "tool_event",
        "event": {
            "type": "tool_end",
            "id": "c2",
            "name": "mark_task_completed",
            "input": {},
            "output": "Progress: 2/2 tasks completed.\nRemaining steps: 0 — all plan tasks are completed.",
        },
    }
    [e async for e in sl._handle_tool_event(start)]
    out = [e async for e in sl._handle_tool_event(end)]
    outcome = next(
        e for e in out if isinstance(e, dict) and e.get("type") == "turn_outcome"
    )
    assert outcome["code"] == "plan_task_completed"
    assert "message" not in outcome
    assert outcome["details"]["plan_tasks_remaining"] is False
    assert not any(s.get("kind") == "status" for s in timeline.segments)


# --- handler -----------------------------------------------------------------


def _patch_handler(monkeypatch, run_stream, synth_calls: List[dict]):
    """Plan already fully done: the loop goes straight to the closing phase."""

    async def fake_fetch(_pid):
        return {"approved_markdown": _PLAN_ALL_DONE, "revision": 4}

    async def fake_session(_pid):
        return "sess-close"

    async def fake_get_agent(*_a, **_k):
        return object(), "test_profile"

    class FakePipe:
        session_id = "sess-close"

        def run_stream(self, *a, **kw):
            return run_stream(*a, **kw)

    async def fake_synth(**kw):
        synth_calls.append(kw)
        return "Fallback summary."

    async def fake_persist(self, **_kw):
        return "fallback-msg"

    async def fake_append(self, **_kw):
        return True

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
    monkeypatch.setattr(PlanExecutionHandler, "_persist_final_summary", fake_persist)
    monkeypatch.setattr(
        PlanExecutionHandler, "_append_summary_to_last_task", fake_append
    )


@pytest.mark.anyio
async def test_handler_closing_turn_uses_tool_outcome(monkeypatch):
    """Closing turn calls the tool: its message becomes the run's final message."""
    calls: List[dict] = []
    synth: List[dict] = []

    async def run_stream(user_input, *a, **kw):
        calls.append({"input": user_input, **kw})
        yield {
            "type": "turn_started",
            "user_message_id": "u-c",
            "assistant_message_id": "a-close",
        }
        yield {
            "type": "turn_outcome",
            "code": "plan_completed",
            "details": {
                "summary": "Articolo pronto.",
                "deliverables": ["workspace/articolo.docx"],
                "assistant_message_id": "a-close",
            },
        }

    _patch_handler(monkeypatch, run_stream, synth)
    entry: Dict[str, Any] = {
        "chat_session_id": "sess-close",
        "owner": "u1",
        "tasks": [],
    }
    phases: List[str] = []
    summary, deliverable = await PlanExecutionHandler()._run_plan_loop(
        "pe-close",
        "execution_plan_close",
        entry,
        on_progress=lambda ev: phases.append(ev.get("phase")),
    )

    assert summary == "Articolo pronto."
    assert deliverable == "workspace/articolo.docx"
    assert entry["summary_message_id"] == "a-close"
    assert synth == []  # no server-side fallback summary
    assert len(calls) == 1
    assert calls[0]["message_source"] == "internal_trigger"
    assert calls[0]["plan_execution_task_id"] is None
    assert "complete_execution_plan" in calls[0]["input"]
    assert phases[-2:] == ["writing", "complete"]


@pytest.mark.anyio
async def test_handler_falls_back_when_plan_not_closed(monkeypatch):
    """Agent never calls the tool (2 attempts): server summary as before."""
    calls: List[dict] = []
    synth: List[dict] = []

    async def run_stream(user_input, *a, **kw):
        calls.append(kw)
        yield {"type": "token", "content": "ok"}

    _patch_handler(monkeypatch, run_stream, synth)
    entry: Dict[str, Any] = {
        "chat_session_id": "sess-close",
        "owner": "u1",
        "tasks": [],
    }
    summary, _ = await PlanExecutionHandler()._run_plan_loop(
        "pe-close2", "execution_plan_close", entry, on_progress=lambda _e: None
    )
    assert len(calls) == 2
    assert summary == "Fallback summary."
    assert synth and entry["summary_message_id"] == "fallback-msg"

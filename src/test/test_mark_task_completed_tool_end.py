"""Plan execution: the ``mark_task_completed`` tool card must end as completed.

Regression tests for the bug where, in a plan-execution task turn
(``message_source="internal_trigger"``), the stream loop interrupted the turn on
the ``mark_task_completed`` ``tool_end`` *before* the generic tool_end handling.
The tool_end was then never forwarded (SSE / timeline) nor persisted as a tool
step, so the chat-ui showed the card stuck on "waiting for the server" forever,
live and after a reload, although the plan had completed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.runtime.stream.loop import StreamLoop, _BreakSignal
from src.runtime.timeline_builder import TimelineBuilder
from src.runtime.tool_step_queue import queue_tool_step


class _FakeTurnPersist:
    """Minimal stand-in for ``TurnPersistence``: queues steps, records flushes."""

    def __init__(self) -> None:
        self.pending_db_steps: List[Dict[str, Any]] = []
        self.pending_step_ids: Dict[str, str] = {}
        self.persist_calls: List[Optional[str]] = []

    def queue_tool_step(self, evt, *, is_error=False, is_start=False) -> None:
        queue_tool_step(
            self.pending_db_steps,
            self.pending_step_ids,
            evt,
            is_error=is_error,
            is_start=is_start,
        )

    async def persist_pending_turn_records(self, message_id, **_kw) -> None:
        self.persist_calls.append(message_id)


def _guards() -> SimpleNamespace:
    """Turn guards with every budget disabled (0) so no hard-stop interferes."""
    return SimpleNamespace(
        max_reasoning_chars=0,
        max_reasoning_events=0,
        max_tool_events=0,
        max_tool_calls=0,
        max_stream_events=0,
        max_control_events=0,
        max_output_events=0,
        max_output_chars=0,
        no_progress_timeout=0,
        min_reasoning_chars_without_tool=0,
        max_reasoning_events_without_tool=0,
        reasoning_hard_stop=False,
        turn_timeout=30,
        state=SimpleNamespace(
            last_progress_at=0.0,
            reasoning_guard_logged=False,
            reasoning_no_tool_warned=False,
        ),
    )


def _make_loop(message_source: str = "internal_trigger"):
    """StreamLoop wired to a real TimelineBuilder (what is saved in history)."""
    persist = _FakeTurnPersist()
    timeline = TimelineBuilder()
    sent: List[Dict[str, Any]] = []

    def track(out: Dict[str, Any]) -> Dict[str, Any]:
        # Same contract as agent_pipeline._track_sse: feed the timeline.
        timeline.apply_chunk(out)
        sent.append(out)
        return out

    sl = StreamLoop(
        queue=asyncio.Queue(),
        stop_event=SimpleNamespace(set=lambda: None, is_set=lambda: False),
        loop=asyncio.get_running_loop(),
        turn_guards=_guards(),
        artifact_parser=None,
        artifact_manager=None,
        turn_persist=persist,
        session_id="sess-mtc",
        profile_name="aion_std",
        user_id="u1",
        assistant_message_id="asst-1",
        message_source=message_source,
        track_sse=track,
        timeline_builder=timeline,
    )
    return sl, persist, timeline, sent


def _tool_chunk(kind: str) -> Dict[str, Any]:
    evt: Dict[str, Any] = {
        "type": kind,
        "id": "call_mtc_1",
        "name": "mark_task_completed",
        "input": {"task_id": "task_04"},
    }
    if kind == "tool_end":
        evt["output"] = "Task task_04 marked completed. All tasks done."
    return {"type": "tool_event", "event": evt}


async def _drain(sl: StreamLoop, chunk: Dict[str, Any]) -> List[Any]:
    return [e async for e in sl._handle_tool_event(chunk)]


@pytest.mark.anyio
async def test_mark_task_completed_tool_end_is_forwarded_and_persisted():
    """Internal plan turn: tool_end reaches SSE + DB before the turn is cut."""
    sl, persist, timeline, sent = _make_loop()

    await _drain(sl, _tool_chunk("tool_start"))
    out = await _drain(sl, _tool_chunk("tool_end"))

    # The tool_end itself is forwarded to the client, before the outcome banner.
    types = [
        (e.get("type"), (e.get("event") or {}).get("type"))
        for e in out
        if isinstance(e, dict)
    ]
    assert ("tool_event", "tool_end") in types
    assert types.index(("tool_event", "tool_end")) < types.index(("turn_outcome", None))
    # ...and the turn is still interrupted afterwards.
    assert isinstance(out[-1], _BreakSignal)
    assert sl.stop_reason == "plan_task_completed"

    # The tool step is closed in the DB queue (update of the start step).
    updates = [s for s in persist.pending_db_steps if s.get("pending_update")]
    assert updates and updates[-1]["step_id"] == "call_mtc_1"
    assert "marked completed" in updates[-1]["output"]
    assert persist.persist_calls  # flushed to the assistant message

    # The persisted timeline no longer has a running tool card.
    tools = [s for s in timeline.segments if s.get("kind") == "tool"]
    assert tools, "tool segment expected in timeline"
    assert all(s.get("status") != "running" for s in tools)


@pytest.mark.anyio
async def test_mark_task_completed_tool_end_emitted_once():
    """The early exit must not also fall through to the generic tool_end path."""
    sl, persist, _timeline, sent = _make_loop()

    await _drain(sl, _tool_chunk("tool_start"))
    await _drain(sl, _tool_chunk("tool_end"))

    ends = [
        e
        for e in sent
        if e.get("type") == "tool_event"
        and (e.get("event") or {}).get("type") == "tool_end"
    ]
    assert len(ends) == 1
    assert len([s for s in persist.pending_db_steps if s.get("pending_update")]) == 1


@pytest.mark.anyio
async def test_mark_task_completed_user_turn_not_interrupted():
    """Outside plan execution (user turn) the tool is a normal tool: no cut."""
    sl, _persist, timeline, _sent = _make_loop(message_source="user_input")

    await _drain(sl, _tool_chunk("tool_start"))
    out = await _drain(sl, _tool_chunk("tool_end"))

    assert not any(isinstance(e, _BreakSignal) for e in out)
    assert not any(isinstance(e, dict) and e.get("type") == "turn_outcome" for e in out)
    tools = [s for s in timeline.segments if s.get("kind") == "tool"]
    assert tools and all(s.get("status") != "running" for s in tools)

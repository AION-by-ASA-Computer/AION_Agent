"""Plan execution job handler — background tasks, progress SSE, final LLM summary."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("aion.plan_execution")

_handler: Optional["PlanExecutionHandler"] = None


def _active_session_profile(chat_session_id: str) -> str:
    """Profile currently active for ``chat_session_id`` ("" when unknown).

    Read from the MCP session context, which ``get_agent`` sets to the profile
    of the last agent built or reused for the chat. Plan execution uses it when
    the request carries no profile, so an approved plan runs with the profile
    selected in the chat instead of a default one (which would build an agent
    with another profile's tools, MCP servers and skills).
    """
    sid = (chat_session_id or "").strip()
    if not sid:
        return ""
    try:
        from src.mcp_manager import mcp_manager

        sctx = mcp_manager.get_session_context(sid)
        return (getattr(sctx, "profile_slug", "") or "").strip() if sctx else ""
    except Exception:
        return ""


async def _get_agent_for_execution(
    profile_name: str,
    *,
    session_id: str,
    user_id: str,
):
    from src.main import get_agent

    return await get_agent(
        profile_name,
        session_id=session_id,
        user_id=user_id,
        agent_mode="normal",
    )


def _make_plan_execution_pipeline(
    agent,
    session_id: str,
    profile_name: str,
    *,
    user_id: str,
    agent_mode: str = "normal",
):
    from src.agent_pipeline import AgentPipeline

    return AgentPipeline(
        agent,
        session_id,
        profile_name,
        user_id=user_id,
        agent_mode=agent_mode,
    )


def _last_task_assistant_id(entry: dict) -> Optional[str]:
    """Assistant message id of the last task in ``entry["tasks"]`` that has one.

    Fallback for ``_run_plan_loop`` when the loop itself ran no task (e.g. a
    resume after every task was already marked done).
    """
    for task in reversed(entry.get("tasks") or []):
        mid = str(task.get("assistant_message_id") or "").strip()
        if mid:
            return mid
    return None


def plan_execution_data_dir() -> Path:
    raw = (os.getenv("AION_PLAN_EXECUTION_DATA_DIR") or "data/plan_execution").strip()
    p = Path(raw)
    p.mkdir(parents=True, exist_ok=True)
    return p


def plan_execution_enabled() -> bool:
    return (os.getenv("AION_PLAN_EXECUTION_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _progress_label(event: dict) -> str:
    phase = str(event.get("phase") or "")
    task_id = (event.get("task_id") or "").strip()
    title = (event.get("title") or "").strip()
    index = event.get("index")
    total = event.get("total")

    if phase == "starting":
        return "Starting plan execution…"
    if phase == "task_start":
        head = f"Task `{task_id}`"
        if title:
            short = title if len(title) <= 90 else title[:87] + "…"
            head = f"{head}: {short}"
        if index and total:
            return f"{head} — in progress ({index}/{total})"
        return f"{head} — in progress"
    if phase == "task_done":
        if index and total:
            return f"Task `{task_id}` completed ({index}/{total})"
        return f"Task `{task_id}` completed"
    if phase == "task_retry":
        if index and total:
            return f"Task `{task_id}` — retry ({index}/{total})"
        return f"Task `{task_id}` — retry"
    if phase == "task_error":
        if index and total:
            return f"Task `{task_id}` failed — skipped ({index}/{total})"
        return f"Task `{task_id}` failed — skipped"
    if phase == "writing":
        return "Writing final comment…"
    if phase == "error":
        return f"Error: {event.get('message') or 'execution interrupted'}"
    if phase == "complete":
        return "Plan completed"
    if phase == "tool":
        return _tool_activity_label(
            str(event.get("tool_name") or ""),
            str(event.get("status") or "running"),
            str(event.get("detail") or ""),
        )
    if phase == "task_turn_started":
        return f"Task `{task_id}` — turno avviato"
    msg = (event.get("message") or "").strip()
    if msg:
        return msg
    return phase or "In progress…"


def _tool_detail_from_input(evt: dict) -> str:
    inp = evt.get("input")
    if isinstance(inp, str):
        try:
            inp = json.loads(inp)
        except Exception:
            return inp.strip()[:120] if inp else ""
    if not isinstance(inp, dict):
        return ""
    for key in (
        "relative_path",
        "path",
        "query",
        "task_id",
        "pattern",
        "url",
        "name",
        "sql",
        "promql",
    ):
        val = str(inp.get(key) or "").strip()
        if val:
            return val[:120]
    return ""


def _tool_activity_label(tool_name: str, status: str, detail: str) -> str:
    tn = (tool_name or "").strip()
    d = (detail or "").strip()
    short = d if len(d) <= 80 else d[:77] + "…"
    done = status in ("done", "ok", "complete")
    err = status in ("error", "tool_error")

    if tn == "sandbox_write_workspace_file":
        base = "Writing file to workspace"
    elif tn == "sandbox_read_workspace_file":
        base = "Reading file dal workspace"
    elif tn == "sandbox_edit_workspace_file":
        base = "Editing file nel workspace"
    elif tn == "mark_task_completed":
        base = "Segno task completed"
    elif tn == "complete_execution_plan":
        base = "Closing plan"
    elif tn == "web_search":
        base = "Web search"
    elif tn == "web_fetch_page":
        base = "Fetching web page"
    elif tn.startswith("memory_"):
        base = "Querying Mnemos memory"
    elif "grep" in tn or "search" in tn or "ripgrep" in tn:
        base = "Searching codebase"
    elif "prometheus" in tn or "promql" in tn:
        base = "Querying metrics"
    elif "grafana" in tn:
        base = "Consulto Grafana"
    elif tn.startswith("sandbox_"):
        base = "Operazione sandbox"
    elif tn:
        base = f"Running {tn}"
    else:
        base = "Operazione agente"

    if short:
        base = f"{base}: {short}"
    if done:
        return f"{base} — done"
    if err:
        return f"{base} — error"
    return base


def _extract_goal(markdown: str) -> str:
    lines = (markdown or "").splitlines()
    mode = False
    buf: List[str] = []
    for raw in lines:
        line = raw.strip()
        sl = line.lower()
        if sl == "## goal":
            mode = True
            continue
        if line.startswith("## ") and sl != "## goal":
            break
        if mode and line:
            buf.append(line)
    return " ".join(buf).strip()[:500]


class PlanExecutionHandler:
    """Background approved-plan execution with task progress activities."""

    def __init__(self) -> None:
        self._active_tasks: Dict[str, dict] = {}
        self._stream_seq: Dict[str, int] = {}
        self._stream_events: Dict[str, asyncio.Event] = {}
        plan_execution_data_dir()

    def _notify_stream(self, run_id: str) -> None:
        self._stream_seq[run_id] = self._stream_seq.get(run_id, 0) + 1
        ev = self._stream_events.get(run_id)
        if ev is not None:
            ev.set()

    def _stream_event(self, run_id: str) -> asyncio.Event:
        if run_id not in self._stream_events:
            self._stream_events[run_id] = asyncio.Event()
        return self._stream_events[run_id]

    async def wait_stream_update(
        self, run_id: str, last_seq: int, *, timeout: float = 0.5
    ) -> int:
        if self._stream_seq.get(run_id, 0) > last_seq:
            return self._stream_seq[run_id]
        ev = self._stream_event(run_id)
        ev.clear()
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        return self._stream_seq.get(run_id, 0)

    def start_plan_execution(
        self,
        plan_id: str,
        *,
        owner: str = "",
        chat_session_id: str = "",
        profile_name: str = "",
    ) -> dict:
        if not plan_execution_enabled():
            raise RuntimeError(
                "Plan execution is disabled (AION_PLAN_EXECUTION_ENABLED=0)"
            )

        pid = (plan_id or "").strip()
        if not pid:
            raise ValueError("plan_id is required")

        run_id = new_plan_execution_run_id()
        # Explicit profile first, then the chat's active profile; the env /
        # aion_std default only when the session has no profile yet.
        profile = (
            (profile_name or "").strip()
            or _active_session_profile(chat_session_id)
            or os.getenv("AION_DEFAULT_PROFILE")
            or "aion_std"
        ).strip()

        entry: Dict[str, Any] = {
            "task": None,
            "future": None,
            "plan_id": pid,
            "profile_name": profile,
            "status": "running",
            "progress": {},
            "activities": [],
            "tasks": [],
            "result": None,
            "deliverable_path": None,
            "started_at": time.time(),
            "owner": (owner or "default").strip() or "default",
            "chat_session_id": (chat_session_id or "").strip(),
            "_cancel": False,
        }
        self._active_tasks[run_id] = entry
        self._persist_running(run_id, entry)

        def on_progress(event: dict) -> None:
            payload = dict(event)
            payload["ts"] = time.time()
            payload["label"] = _progress_label(payload)
            entry["progress"] = payload
            activities: List[dict] = entry.setdefault("activities", [])
            activities.append(payload)
            if len(activities) > 100:
                entry["activities"] = activities[-100:]
            self._notify_stream(run_id)
            if payload.get("phase") == "task_start" and payload.get("task_id"):
                tasks = entry.setdefault("tasks", [])
                tid = str(payload["task_id"])
                if not any(t.get("task_id") == tid for t in tasks):
                    tasks.append(
                        {
                            "task_id": tid,
                            "title": payload.get("title") or "",
                            "status": "running",
                        }
                    )
            if payload.get("phase") == "task_done" and payload.get("task_id"):
                tid = str(payload["task_id"])
                for t in entry.get("tasks") or []:
                    if t.get("task_id") == tid:
                        t["status"] = "done"
            self._persist_running(run_id, entry)

        async def _run() -> None:
            try:
                summary, deliverable = await self._run_plan_loop(
                    run_id,
                    pid,
                    entry,
                    on_progress=on_progress,
                )
                if entry.get("status") == "paused":
                    return
                entry["result"] = summary
                entry["deliverable_path"] = deliverable
                entry["status"] = "done"
                self._save_result(run_id, entry)
            except asyncio.CancelledError:
                if entry.get("_pause_intent"):
                    entry["status"] = "paused"
                    entry["result"] = (
                        "Plan execution paused. Resume from the Plan panel to continue."
                    )
                else:
                    entry["status"] = "cancelled"
                    entry["result"] = (
                        "Plan execution cancelled. Resume from the Plan panel to continue."
                    )
                entry.pop("_pause_intent", None)
                self._save_result(run_id, entry)
                raise
            except Exception as exc:
                logger.error(
                    "Plan execution failed run=%s plan=%s: %s",
                    run_id,
                    pid,
                    exc,
                    exc_info=True,
                )
                entry["status"] = "error"
                entry["result"] = str(exc)
                on_progress({"phase": "error", "message": str(exc)})
                self._save_result(run_id, entry)

        self._schedule_background_coro(entry, _run())
        return {
            "run_id": run_id,
            "status": "running",
            "plan_id": pid,
            "ui_event": "plan_execution_started",
        }

    def _schedule_background_coro(self, entry: dict, coro) -> None:
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                entry["task"] = asyncio.create_task(coro)
                return
        except RuntimeError:
            pass

        from src.main import _GLOBAL_LOOP

        main_loop = _GLOBAL_LOOP
        if main_loop is None or not main_loop.is_running():
            raise RuntimeError(
                "Plan execution event loop unavailable; use POST /plan-execution/start"
            )
        entry["future"] = asyncio.run_coroutine_threadsafe(coro, main_loop)

    async def _run_plan_loop(
        self,
        run_id: str,
        plan_id: str,
        entry: dict,
        *,
        on_progress: Callable[[dict], None],
    ) -> tuple[str, Optional[str]]:
        from src.a2a.plan_markdown import iter_plan_task_rows
        from src.runtime import orchestration_db as odb
        from src.runtime.plan_engine import next_pending_task_id
        from src.runtime.plan_execution import (
            build_plan_execution_trigger,
            infer_deliverable_path,
            resolve_existing_deliverable,
            task_title_from_markdown,
        )

        chat_session_id = entry.get("chat_session_id") or ""
        owner = entry.get("owner") or "default"
        profile_name = entry.get("profile_name") or "aion_std"

        stored_sess = await odb.fetch_plan_session(plan_id)
        if stored_sess and chat_session_id and stored_sess != chat_session_id:
            raise RuntimeError("plan does not belong to this session")

        on_progress({"phase": "starting", "plan_id": plan_id})

        agent, resolved_profile = await _get_agent_for_execution(
            profile_name,
            session_id=chat_session_id or stored_sess or "plan-exec",
            user_id=owner,
        )
        pipe = _make_plan_execution_pipeline(
            agent,
            chat_session_id or stored_sess or "plan-exec",
            resolved_profile,
            user_id=owner,
            agent_mode="normal",
        )

        # Assistant message of the last task completed by this loop: the final
        # summary is also written there (see _append_summary_to_last_task).
        last_task_asst_id: Optional[str] = None

        while True:
            if entry.get("_cancel"):
                raise asyncio.CancelledError()

            rec = await odb.fetch_plan_record(plan_id)
            approved_md = (rec.get("approved_markdown") or "").strip() if rec else ""
            if not rec or not approved_md:
                raise RuntimeError("plan not approved or missing markdown")

            task_id = next_pending_task_id(approved_md)
            if not task_id:
                break

            rows = iter_plan_task_rows(approved_md)
            total = len(rows)
            done_count = sum(1 for _, _, done in rows if done)
            title = task_title_from_markdown(approved_md, task_id)
            index = done_count + 1

            on_progress(
                {
                    "phase": "task_start",
                    "plan_id": plan_id,
                    "task_id": task_id,
                    "title": title,
                    "index": index,
                    "total": total,
                }
            )

            sub_completed = False
            task_user_id: Optional[str] = None
            task_asst_id: Optional[str] = None
            # Set when an attempt ended with reasoning only (no answer, no tool
            # call): the model spent its whole output budget thinking. Retrying
            # with the same settings fails the same way, so the retry runs with
            # thinking disabled (reasoning_effort="off").
            reasoning_stalled = False
            for attempt in range(2):
                if attempt > 0:
                    on_progress(
                        {
                            "phase": "task_retry",
                            "plan_id": plan_id,
                            "task_id": task_id,
                            "index": index,
                            "total": total,
                            "message": f"task `{task_id}` — nuovo tentativo ({attempt + 1}/2)",
                        }
                    )
                trigger = build_plan_execution_trigger(task_id, attempt=attempt)
                # None keeps the session/profile default; "off" only after a stall.
                turn_effort = "off" if reasoning_stalled else None
                if reasoning_stalled:
                    logger.info(
                        "Plan execution run=%s task=%s: previous attempt produced "
                        "reasoning only — retrying with thinking off.",
                        run_id,
                        task_id,
                    )
                reasoning_stalled = False
                sub_completed = False
                turn_finished = False
                async for chunk in pipe.run_stream(
                    trigger,
                    reasoning_effort=turn_effort,
                    message_source="internal_trigger",
                    plan_id=plan_id,
                    plan_execution_task_id=task_id,
                ):
                    if entry.get("_cancel"):
                        raise asyncio.CancelledError()
                    if turn_finished:
                        continue
                    if chunk.get("type") == "turn_started":
                        task_user_id = (
                            chunk.get("user_message_id") or ""
                        ).strip() or None
                        task_asst_id = (
                            chunk.get("assistant_message_id") or ""
                        ).strip() or None
                        for t in entry.get("tasks") or []:
                            if t.get("task_id") == task_id:
                                if task_user_id:
                                    t["user_message_id"] = task_user_id
                                if task_asst_id:
                                    t["assistant_message_id"] = task_asst_id
                                break
                        self._persist_running(run_id, entry)
                        on_progress(
                            {
                                "phase": "task_turn_started",
                                "plan_id": plan_id,
                                "task_id": task_id,
                                "user_message_id": task_user_id,
                                "assistant_message_id": task_asst_id,
                                "tasks": list(entry.get("tasks") or []),
                            }
                        )
                    if chunk.get("type") == "tool_event" and not turn_finished:
                        evt = chunk.get("event") or {}
                        et = str(evt.get("type") or "")
                        if et in ("tool_start", "tool_end", "tool_error"):
                            tool_status = (
                                "running"
                                if et == "tool_start"
                                else ("error" if et == "tool_error" else "done")
                            )
                            on_progress(
                                {
                                    "phase": "tool",
                                    "plan_id": plan_id,
                                    "task_id": task_id,
                                    "tool_name": str(evt.get("name") or ""),
                                    "status": tool_status,
                                    "detail": _tool_detail_from_input(evt),
                                }
                            )
                    if (
                        chunk.get("type") == "turn_outcome"
                        and chunk.get("code") == "plan_task_completed"
                    ):
                        sub_completed = True
                        turn_finished = True
                    # Diagnostic outcomes from src/runtime/turn_diagnostics.py
                    # for a turn that produced only reasoning.
                    if chunk.get("type") == "turn_outcome" and chunk.get("code") in (
                        "reasoning_only_no_answer",
                        "reasoning_budget_no_answer",
                    ):
                        reasoning_stalled = True
                if sub_completed:
                    break

            for t in entry.get("tasks") or []:
                if t.get("task_id") == task_id:
                    if task_user_id or task_asst_id:
                        turn: dict = {}
                        if task_user_id:
                            turn["user_message_id"] = task_user_id
                            t["user_message_id"] = task_user_id
                        if task_asst_id:
                            turn["assistant_message_id"] = task_asst_id
                            t["assistant_message_id"] = task_asst_id
                        turns = list(t.get("turns") or [])
                        turns.append(turn)
                        t["turns"] = turns
                    if not sub_completed:
                        t["status"] = "error"
                    break
            self._persist_running(run_id, entry)

            if not sub_completed:
                logger.warning(
                    "Plan execution run=%s plan=%s: task `%s` not completed after retry — paused.",
                    run_id,
                    plan_id,
                    task_id,
                )
                on_progress(
                    {
                        "phase": "task_error",
                        "plan_id": plan_id,
                        "task_id": task_id,
                        "index": index,
                        "total": total,
                        "message": f"task `{task_id}` not completed after retry — paused",
                    }
                )
                entry["status"] = "paused"
                entry["result"] = (
                    f"Plan execution paused: task `{task_id}` was not completed. "
                    "Resume from the Plan panel to continue."
                )
                self._save_result(run_id, entry)
                return entry.get("result") or "", infer_deliverable_path(approved_md)

            last_task_asst_id = task_asst_id or last_task_asst_id
            rec_after = await odb.fetch_plan_record(plan_id)
            rev = int(rec_after.get("revision") or 1) if rec_after else 1
            for t in entry.get("tasks") or []:
                if t.get("task_id") == task_id:
                    t["status"] = "done"
                    break
            on_progress(
                {
                    "phase": "task_done",
                    "plan_id": plan_id,
                    "task_id": task_id,
                    "revision": rev,
                    "index": index,
                    "total": total,
                }
            )

        rec_final = await odb.fetch_plan_record(plan_id)
        final_md = (
            (rec_final.get("approved_markdown") or "").strip() if rec_final else ""
        )
        summary_session = chat_session_id or stored_sess or ""
        # The plan text may name a file the agent never produced (or only the
        # template example): prefer what really exists in the session workspace.
        deliverable = (
            resolve_existing_deliverable(
                summary_session, infer_deliverable_path(final_md)
            )
            if final_md
            else None
        )
        goal = _extract_goal(final_md)

        # "writing" tells the chat-ui that no task turn will stream any more
        # (it releases its stream recovery); the closing turn below and the
        # fallback summary both belong to this phase.
        on_progress({"phase": "writing", "plan_id": plan_id})

        # Preferred path: a closing agent turn calls complete_execution_plan,
        # which writes the summary as a regular assistant message and renders
        # one card per generated document (persisted as attachments).
        closing = await self._run_closing_turn(
            pipe, plan_id=plan_id, entry=entry, on_progress=on_progress
        )
        if closing is not None:
            summary = str(closing.get("summary") or "").strip()
            paths = [p for p in (closing.get("deliverables") or []) if p]
            deliverable = paths[0] if paths else deliverable
            entry["summary_message_id"] = closing.get("assistant_message_id")
            on_progress(
                {"phase": "complete", "plan_id": plan_id, "message": "Plan completed"}
            )
            return summary, deliverable

        # Fallback (agent did not close the plan): LLM summary saved by the
        # server, as before the closing tool existed.
        summary = await self._synthesize_final_summary(
            plan_id=plan_id,
            goal=goal,
            plan_markdown=final_md,
            deliverable_path=deliverable,
            on_text=self._summary_publisher(run_id, entry),
        )
        # Persist the final message server-side (with the deliverable attached)
        # so it survives reloads and shows the file card; the chat-ui only
        # falls back to saving it itself when this id is missing.
        entry["summary_message_id"] = await self._persist_final_summary(
            session_id=summary_session,
            summary=summary,
            deliverable_path=deliverable,
            profile_name=str(entry.get("profile_name") or "default"),
            owner=owner,
        )
        # The last task's turn ends on mark_task_completed, usually with no (or
        # only placeholder) text: write the summary there too, so the task chat
        # shows the plan outcome and not just the tool call.
        await self._append_summary_to_last_task(
            session_id=summary_session,
            message_id=last_task_asst_id or _last_task_assistant_id(entry),
            summary=summary,
        )
        on_progress(
            {"phase": "complete", "plan_id": plan_id, "message": "Plan completed"}
        )
        return summary, deliverable

    async def _run_closing_turn(
        self,
        pipe,
        *,
        plan_id: str,
        entry: dict,
        on_progress: Callable[[dict], None],
        attempts: int = 2,
    ) -> Optional[dict]:
        """Run the plan-closing agent turn (after the last task) and return its outcome.

        The turn is an ``internal_trigger`` turn with no task id: ``turn_context``
        then injects the closing reminder (``build_plan_completion_reminder``)
        and the agent is asked to call ``complete_execution_plan``. The stream
        loop turns that call into the final answer (summary + document cards)
        and emits ``turn_outcome`` ``plan_completed``, whose ``details`` are
        returned here (``summary``, ``deliverables``, ``assistant_message_id``).

        Returns None when the agent never closed the plan after ``attempts``
        turns, or on error: the caller falls back to the server-side summary.
        Tool activity is forwarded to the progress feed like task turns.
        """
        from src.runtime.plan_execution import build_plan_completion_trigger

        for attempt in range(max(1, attempts)):
            details: Optional[dict] = None
            asst_id: Optional[str] = None
            try:
                async for chunk in pipe.run_stream(
                    build_plan_completion_trigger(plan_id),
                    message_source="internal_trigger",
                    plan_id=plan_id,
                    plan_execution_task_id=None,
                ):
                    if entry.get("_cancel"):
                        raise asyncio.CancelledError()
                    ctype = chunk.get("type")
                    if ctype == "turn_started":
                        asst_id = (
                            chunk.get("assistant_message_id") or ""
                        ).strip() or None
                    elif ctype == "tool_event" and details is None:
                        evt = chunk.get("event") or {}
                        et = str(evt.get("type") or "")
                        if et in ("tool_start", "tool_end", "tool_error"):
                            on_progress(
                                {
                                    "phase": "tool",
                                    "plan_id": plan_id,
                                    "tool_name": str(evt.get("name") or ""),
                                    "status": "running"
                                    if et == "tool_start"
                                    else ("error" if et == "tool_error" else "done"),
                                    "detail": _tool_detail_from_input(evt),
                                }
                            )
                    elif (
                        ctype == "turn_outcome"
                        and chunk.get("code") == "plan_completed"
                    ):
                        raw = chunk.get("details")
                        details = dict(raw) if isinstance(raw, dict) else {}
                    # Keep consuming after the outcome: the pipeline persists the
                    # message and clears stream_active in its own finally.
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Plan execution plan=%s: closing turn failed (attempt %s): %s",
                    plan_id,
                    attempt + 1,
                    exc,
                )
                continue
            if details is not None:
                # The stream loop sends its message id; turn_started is the backup.
                if not details.get("assistant_message_id"):
                    details["assistant_message_id"] = asst_id
                return details
            logger.info(
                "Plan execution plan=%s: closing turn ended without "
                "complete_execution_plan (attempt %s/%s)",
                plan_id,
                attempt + 1,
                attempts,
            )
        return None

    async def _append_summary_to_last_task(
        self,
        *,
        session_id: str,
        message_id: Optional[str],
        summary: str,
    ) -> bool:
        """Write the final plan summary into the last task's assistant message.

        Placeholder bodies (``PLAN_TASK_PLACEHOLDER_TEXTS``) are replaced, real
        task output is kept and the summary appended below it. Best effort:
        failures are logged and never fail the run (the summary is still saved
        as its own message in the plan session).
        """
        if not session_id or not message_id or not (summary or "").strip():
            return False
        try:
            from src.api.history import history_manager
            from src.runtime.turn_diagnostics import PLAN_TASK_PLACEHOLDER_TEXTS

            return await history_manager.append_message_text(
                session_id,
                message_id,
                summary,
                replaceable_texts=PLAN_TASK_PLACEHOLDER_TEXTS,
            )
        except Exception as exc:
            logger.warning(
                "Plan execution: could not write summary into task message %s: %s",
                message_id,
                exc,
            )
            return False

    def _summary_publisher(self, run_id: str, entry: dict) -> Callable[[str], None]:
        """Build the ``on_text`` callback that streams the final summary to the UI.

        The partial text goes into ``entry["progress"]["summary_partial"]`` (not
        persisted, not added to activities) and wakes the SSE status stream,
        which forwards it to the chat-ui as a live preview. Throttled (~40 new
        chars or 300 ms) because every SSE payload carries the full status.
        """
        state = {"at": 0.0, "chars": 0}

        def publish(text: str) -> None:
            now = time.monotonic()
            if len(text) - state["chars"] < 40 and now - state["at"] < 0.3:
                return
            state["at"] = now
            state["chars"] = len(text)
            progress = dict(entry.get("progress") or {})
            progress["summary_partial"] = text
            entry["progress"] = progress
            self._notify_stream(run_id)

        return publish

    async def _persist_final_summary(
        self,
        *,
        session_id: str,
        summary: str,
        deliverable_path: Optional[str],
        profile_name: str,
        owner: str,
    ) -> Optional[str]:
        """Save the final summary as an assistant message, deliverable attached.

        Returns the new message id, or None when there is no chat session or the
        write fails (the chat-ui then saves the summary itself, without file).
        The attachment uses the session-relative path as ``storage_key``, the
        same form as artifacts saved during normal turns, so the chat renders
        its download card.
        """
        if not session_id or not (summary or "").strip():
            return None
        try:
            import mimetypes

            from src.api.history import history_manager
            from src.data.ids import new_uuid7_str

            message_id = new_uuid7_str()
            await history_manager.add_message(
                session_id,
                "assistant",
                summary,
                profile_name=profile_name,
                user_id=owner,
                message_id=message_id,
            )
            # Attach the main deliverable first, then the other documents of
            # the workspace (same detection as complete_execution_plan), so the
            # fallback message also shows every generated document.
            from src.runtime.orchestration_tools import collect_plan_deliverables

            files = collect_plan_deliverables(
                session_id, [deliverable_path] if deliverable_path else None
            )
            others = collect_plan_deliverables(session_id, None)
            seen = {f["path"] for f in files}
            files += [f for f in others if f["path"] not in seen]
            for f in files:
                # collect_plan_deliverables only returns real files inside
                # the session folder.
                await history_manager.add_attachment(
                    session_id,
                    storage_key=f["path"],
                    original_name=f["name"],
                    mime=f.get("mime")
                    or mimetypes.guess_type(f["name"])[0]
                    or "application/octet-stream",
                    size_bytes=int(f.get("size_bytes") or 0),
                    kind="artifact",
                    message_id=message_id,
                )
            return message_id
        except Exception as exc:
            logger.warning(
                "Plan execution: could not persist final summary for session %s: %s",
                session_id,
                exc,
            )
            return None

    async def _synthesize_final_summary(
        self,
        *,
        plan_id: str,
        goal: str,
        plan_markdown: str,
        deliverable_path: Optional[str],
        on_text: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Write the user-facing completion message (LLM, markdown).

        ``on_text`` receives the message as it streams — header included, so the
        live preview matches the final text — for the chat-ui preview.
        """
        from src.research.llm_bridge import complete_messages

        header = f"## Plan completed — `{plan_id}`\n\n"
        if deliverable_path:
            header += f"**Deliverable:** `{deliverable_path}`\n\n"
        deliverable = deliverable_path or "workspace/deliverable.md"
        prompt = (
            f"The execution plan `{plan_id}` has been fully completed.\n\n"
            f"**Goal:** {goal or '(see plan)'}\n"
            f"**Deliverable file:** `{deliverable}`\n\n"
            "**Plan state (markdown):**\n"
            f"{(plan_markdown or '')[:12000]}\n\n"
            "Write a mandatory final comment for the user in English (markdown). "
            "Summarize what was accomplished, where to find the deliverable, "
            "and any suggested next steps. Keep it concise (2–4 short paragraphs). "
            "Do not list every tool call."
        )
        text = await complete_messages(
            [
                {
                    "role": "system",
                    "content": "You write clear execution summaries for completed plans.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=2048,
            timeout=120.0,
            on_text=(lambda partial: on_text(header + partial)) if on_text else None,
        )
        if not (text or "").strip():
            return (
                f"✅ Plan `{plan_id}` completato.\n\n"
                f"Deliverable: `{deliverable}`\n\n"
                f"**Goal:** {goal or 'see plan in the Plan panel.'}"
            )
        return header + text.strip()

    def get_status(self, run_id: str) -> Optional[dict]:
        if run_id in self._active_tasks:
            entry = self._active_tasks[run_id]
            return self._status_payload(run_id, entry)
        path = plan_execution_data_dir() / f"{run_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("consumed"):
                    return None
                st = data.get("status", "done")
                if st == "running":
                    self._recover_orphaned_session(run_id, data)
                    st = data.get("status", "done")
                return {
                    "status": st,
                    "plan_id": data.get("plan_id", ""),
                    "goal": data.get("goal", ""),
                    "progress": data.get("progress") or {},
                    "activities": list(data.get("activities") or []),
                    "tasks": list(data.get("tasks") or []),
                    "started_at": data.get("started_at", 0),
                    "chat_session_id": data.get("chat_session_id") or "",
                }
            except Exception:
                pass
        return None

    def list_active_for_owner(
        self, owner: str, *, chat_session_id: Optional[str] = None
    ) -> List[dict]:
        self._recover_stale_running_on_disk()
        seen: set[str] = set()
        items: List[dict] = []
        for rid, entry in self._active_tasks.items():
            if entry.get("owner") != owner or entry.get("status") != "running":
                continue
            if not self._matches_chat_session(entry, chat_session_id):
                continue
            seen.add(rid)
            items.append(self._active_job_payload(rid, entry))
        for path in plan_execution_data_dir().glob("*.json"):
            rid = path.stem
            if rid in seen:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("owner") != owner or data.get("status") != "running":
                continue
            if not self._matches_chat_session(data, chat_session_id):
                continue
            if rid not in self._active_tasks:
                self._recover_orphaned_session(rid, data)
                if data.get("status") != "running":
                    continue
            entry = self._active_tasks.get(rid)
            if entry and entry.get("status") == "running":
                items.append(self._active_job_payload(rid, entry))
        items.sort(key=lambda x: x.get("started_at") or 0, reverse=True)
        return items

    def list_runs_for_owner(
        self,
        owner: str,
        *,
        chat_session_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[dict]:
        """Recent plan execution runs for owner (running + completed on disk)."""
        cap = max(1, min(limit, 50))
        seen: set[str] = set()
        items: List[dict] = []

        def _append(rid: str, data: dict) -> None:
            if rid in seen:
                return
            if data.get("owner") != owner:
                return
            if not self._matches_chat_session(data, chat_session_id):
                return
            if data.get("consumed"):
                return
            seen.add(rid)
            items.append(
                {
                    "run_id": rid,
                    "plan_id": data.get("plan_id", ""),
                    "status": data.get("status", ""),
                    "started_at": data.get("started_at", 0),
                    "completed_at": data.get("completed_at"),
                    "chat_session_id": data.get("chat_session_id") or "",
                    "tasks": list(data.get("tasks") or []),
                }
            )

        for rid, entry in self._active_tasks.items():
            _append(
                rid,
                {
                    "plan_id": entry.get("plan_id"),
                    "status": entry.get("status", "running"),
                    "started_at": entry.get("started_at", 0),
                    "owner": entry.get("owner", ""),
                    "chat_session_id": entry.get("chat_session_id") or "",
                    "tasks": list(entry.get("tasks") or []),
                },
            )

        for path in plan_execution_data_dir().glob("*.json"):
            rid = path.stem
            if rid in seen:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            _append(rid, data)

        items.sort(key=lambda x: x.get("started_at") or 0, reverse=True)
        return items[:cap]

    def cancel_plan_execution(self, run_id: str) -> bool:
        entry = self._active_tasks.get(run_id)
        if not entry or entry.get("status") != "running":
            data = self.load_json(run_id)
            if not data or data.get("status") == "running":
                return False
            data["status"] = "cancelled"
            data["result"] = (
                "Plan execution cancelled. Resume from the Plan panel to continue."
            )
            data["completed_at"] = time.time()
            path = plan_execution_data_dir() / f"{run_id}.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return True
        entry.pop("_pause_intent", None)
        entry["_cancel"] = True
        task = entry.get("task")
        if task and not task.done():
            task.cancel()
        future = entry.get("future")
        if future and not future.done():
            future.cancel()
        entry["status"] = "cancelled"
        entry["result"] = (
            "Plan execution cancelled. Resume from the Plan panel to continue."
        )
        self._save_result(run_id, entry)
        return True

    def pause_plan_execution(self, run_id: str) -> bool:
        entry = self._active_tasks.get(run_id)
        if not entry or entry.get("status") != "running":
            return False
        entry["_pause_intent"] = True
        entry["_cancel"] = True
        task = entry.get("task")
        if task and not task.done():
            task.cancel()
        future = entry.get("future")
        if future and not future.done():
            future.cancel()
        return True

    def resume_plan_execution(self, run_id: str) -> dict:
        entry = self._active_tasks.get(run_id)
        if entry is None:
            data = self.load_json(run_id) or {}
            if not data:
                raise ValueError("plan execution run not found")
            entry = {
                "plan_id": data.get("plan_id"),
                "profile_name": data.get("profile_name") or "aion_std",
                "status": data.get("status"),
                "progress": data.get("progress") or {},
                "activities": list(data.get("activities") or []),
                "tasks": list(data.get("tasks") or []),
                "result": data.get("result"),
                "deliverable_path": data.get("deliverable_path"),
                "started_at": data.get("started_at") or time.time(),
                "owner": data.get("owner") or "default",
                "chat_session_id": data.get("chat_session_id") or "",
                "task": None,
                "future": None,
                "_cancel": False,
            }
            self._active_tasks[run_id] = entry

        st = (entry.get("status") or "").strip()
        if st == "running":
            return {
                "run_id": run_id,
                "status": "running",
                "plan_id": entry.get("plan_id", ""),
                "ui_event": "plan_execution_resumed",
            }
        if st not in ("paused", "cancelled", "interrupted", "error"):
            raise RuntimeError(f"cannot resume plan execution from status `{st}`")

        pid = (entry.get("plan_id") or "").strip()
        if not pid:
            raise ValueError("plan_id missing on run")

        entry["_cancel"] = False
        entry.pop("_pause_intent", None)
        entry["status"] = "running"
        entry.pop("completed_at", None)

        def on_progress(event: dict) -> None:
            payload = dict(event)
            payload["ts"] = time.time()
            payload["label"] = _progress_label(payload)
            entry["progress"] = payload
            activities: List[dict] = entry.setdefault("activities", [])
            activities.append(payload)
            if len(activities) > 100:
                entry["activities"] = activities[-100:]
            self._notify_stream(run_id)
            if payload.get("phase") == "task_start" and payload.get("task_id"):
                tasks = entry.setdefault("tasks", [])
                tid = str(payload["task_id"])
                if not any(t.get("task_id") == tid for t in tasks):
                    tasks.append(
                        {
                            "task_id": tid,
                            "title": payload.get("title") or "",
                            "status": "running",
                        }
                    )
            if payload.get("phase") == "task_done" and payload.get("task_id"):
                tid = str(payload["task_id"])
                for t in entry.get("tasks") or []:
                    if t.get("task_id") == tid:
                        t["status"] = "done"
            self._persist_running(run_id, entry)

        async def _run() -> None:
            try:
                summary, deliverable = await self._run_plan_loop(
                    run_id,
                    pid,
                    entry,
                    on_progress=on_progress,
                )
                if entry.get("status") == "paused":
                    return
                entry["result"] = summary
                entry["deliverable_path"] = deliverable
                entry["status"] = "done"
                self._save_result(run_id, entry)
            except asyncio.CancelledError:
                if entry.get("_pause_intent"):
                    entry["status"] = "paused"
                    entry["result"] = (
                        "Plan execution paused. Resume from the Plan panel to continue."
                    )
                else:
                    entry["status"] = "cancelled"
                    entry["result"] = (
                        "Plan execution cancelled. Resume from the Plan panel to continue."
                    )
                entry.pop("_pause_intent", None)
                self._save_result(run_id, entry)
                raise
            except Exception as exc:
                logger.error(
                    "Plan execution resume failed run=%s plan=%s: %s",
                    run_id,
                    pid,
                    exc,
                    exc_info=True,
                )
                entry["status"] = "error"
                entry["result"] = str(exc)
                on_progress({"phase": "error", "message": str(exc)})
                self._save_result(run_id, entry)

        self._schedule_background_coro(entry, _run())
        return {
            "run_id": run_id,
            "status": "running",
            "plan_id": pid,
            "ui_event": "plan_execution_resumed",
        }

    def get_result(self, run_id: str) -> Optional[str]:
        entry = self._active_tasks.get(run_id)
        if entry and entry.get("status") in ("done", "error", "cancelled"):
            return entry.get("result")
        path = plan_execution_data_dir() / f"{run_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("consumed"):
                    return None
                return data.get("result")
            except Exception:
                pass
        return None

    def get_deliverable_path(self, run_id: str) -> Optional[str]:
        entry = self._active_tasks.get(run_id)
        if entry:
            return entry.get("deliverable_path")
        data = self.load_json(run_id)
        return data.get("deliverable_path") if data else None

    def clear_result(self, run_id: str) -> None:
        self._active_tasks.pop(run_id, None)
        path = plan_execution_data_dir() / f"{run_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["consumed"] = True
                path.write_text(json.dumps(data), encoding="utf-8")
            except Exception:
                pass

    def load_json(self, run_id: str) -> Optional[dict]:
        path = plan_execution_data_dir() / f"{run_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def owns(self, run_id: str, owner: str) -> bool:
        entry = self._active_tasks.get(run_id)
        if entry is not None:
            return entry.get("owner", "") == owner
        data = self.load_json(run_id)
        if data is None:
            return False
        return data.get("owner", "") == owner

    @staticmethod
    def _matches_chat_session(data: dict, chat_session_id: Optional[str]) -> bool:
        if not chat_session_id:
            return True
        cid = (data.get("chat_session_id") or "").strip()
        return bool(cid) and cid == chat_session_id.strip()

    @staticmethod
    def _status_payload(run_id: str, entry: dict) -> dict:
        return {
            "run_id": run_id,
            "status": entry.get("status", "running"),
            "plan_id": entry.get("plan_id", ""),
            "goal": entry.get("goal", ""),
            "progress": entry.get("progress") or {},
            "activities": list(entry.get("activities") or []),
            "tasks": list(entry.get("tasks") or []),
            "started_at": entry.get("started_at", 0),
            "chat_session_id": entry.get("chat_session_id") or "",
        }

    @staticmethod
    def _active_job_payload(run_id: str, entry: dict) -> dict:
        return {
            "run_id": run_id,
            "plan_id": entry.get("plan_id", ""),
            "status": entry.get("status", "running"),
            "progress": entry.get("progress") or {},
            "activities": list(entry.get("activities") or []),
            "tasks": list(entry.get("tasks") or []),
            "started_at": entry.get("started_at", 0),
            "chat_session_id": entry.get("chat_session_id") or "",
        }

    def _persist_running(self, run_id: str, entry: dict) -> None:
        if entry.get("status") != "running":
            return
        path = plan_execution_data_dir() / f"{run_id}.json"
        try:
            data = {
                "plan_id": entry.get("plan_id"),
                "status": "running",
                "progress": entry.get("progress") or {},
                "activities": list(entry.get("activities") or [])[-100:],
                "tasks": list(entry.get("tasks") or []),
                "started_at": entry.get("started_at"),
                "owner": entry.get("owner", ""),
                "chat_session_id": entry.get("chat_session_id") or "",
                "profile_name": entry.get("profile_name", ""),
            }
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug("persist running plan execution %s: %s", run_id, e)

    def _save_result(self, run_id: str, entry: dict) -> None:
        try:
            path = plan_execution_data_dir() / f"{run_id}.json"
            data = {
                "plan_id": entry.get("plan_id"),
                "status": entry.get("status"),
                "result": entry.get("result"),
                "deliverable_path": entry.get("deliverable_path"),
                # Id of the final summary message saved server-side (with the
                # deliverable attached); None when the chat-ui must save it.
                "summary_message_id": entry.get("summary_message_id"),
                "progress": entry.get("progress") or {},
                "activities": list(entry.get("activities") or [])[-100:],
                "tasks": list(entry.get("tasks") or []),
                "started_at": entry.get("started_at"),
                "completed_at": time.time(),
                "owner": entry.get("owner", ""),
                "chat_session_id": entry.get("chat_session_id") or "",
                "profile_name": entry.get("profile_name", ""),
            }
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            logger.info("Plan execution saved to %s", path)
        except Exception as e:
            logger.error("Failed to save plan execution: %s", e)

    def _recover_stale_running_on_disk(self) -> None:
        for path in plan_execution_data_dir().glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("status") != "running":
                continue
            rid = path.stem
            if (
                rid in self._active_tasks
                and self._active_tasks[rid].get("status") == "running"
            ):
                continue
            self._recover_orphaned_session(rid, data)

    def _recover_orphaned_session(self, run_id: str, data: dict) -> None:
        if data.get("status") != "running":
            return
        if run_id in self._active_tasks:
            return
        data["status"] = "interrupted"
        data["result"] = (
            "Plan execution interrupted (server restart or lost session). "
            "Resume from the Plan panel to continue."
        )
        data["completed_at"] = time.time()
        try:
            path = plan_execution_data_dir() / f"{run_id}.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            logger.warning(
                "Plan execution orphaned run=%s — marked interrupted", run_id
            )
        except Exception as e:
            logger.error("recover orphaned plan execution %s: %s", run_id, e)


def get_plan_execution_handler() -> PlanExecutionHandler:
    global _handler
    if _handler is None:
        _handler = PlanExecutionHandler()
    return _handler


def new_plan_execution_run_id(prefix: str = "pe") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"

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
    elif tn.startswith("mempalace_"):
        base = "Querying MemPalace"
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
        profile = (
            profile_name or os.getenv("AION_DEFAULT_PROFILE") or "aion_std"
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
                entry["result"] = summary
                entry["deliverable_path"] = deliverable
                entry["status"] = "done"
                self._save_result(run_id, entry)
            except asyncio.CancelledError:
                entry["status"] = "cancelled"
                entry["result"] = "Plan execution cancelled."
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
            infer_deliverable_path,
            task_title_from_markdown,
        )

        chat_session_id = entry.get("chat_session_id") or ""
        owner = entry.get("owner") or "default"
        profile_name = entry.get("profile_name") or "aion_std"

        stored_sess = await odb.fetch_plan_session(plan_id)
        if stored_sess and chat_session_id and stored_sess != chat_session_id:
            raise RuntimeError("plan does not belong to this session")

        on_progress({"phase": "starting", "plan_id": plan_id})

        from src.main import get_agent
        from src.agent_pipeline import AgentPipeline

        agent, resolved_profile = await get_agent(
            profile_name,
            session_id=chat_session_id or stored_sess or "plan-exec",
            user_id=owner,
            agent_mode="normal",
        )
        pipe = AgentPipeline(
            agent,
            chat_session_id or stored_sess or "plan-exec",
            resolved_profile,
            user_id=owner,
            agent_mode="normal",
        )

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
                trigger = (
                    f"Execute ONLY task `{task_id}`."
                    if attempt == 0
                    else (
                        f"Execute ONLY task `{task_id}`. "
                        "You MUST call mark_task_completed with this task_id before ending the turn."
                    )
                )
                sub_completed = False
                async for chunk in pipe.run_stream(
                    trigger,
                    message_source="internal_trigger",
                    plan_id=plan_id,
                    plan_execution_task_id=task_id,
                ):
                    if entry.get("_cancel"):
                        raise asyncio.CancelledError()
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
                    if chunk.get("type") == "tool_event":
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
                    "Plan execution run=%s plan=%s: task `%s` not completed after retry — skipping.",
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
                        "message": f"task `{task_id}` not completed after retry — skipped",
                    }
                )
                # Mark the task done in the DB so the loop advances rather than looping forever.
                try:
                    from src.runtime.orchestration_tools import run_mark_task_completed

                    await run_mark_task_completed(
                        plan_id,
                        task_id,
                        session_id=chat_session_id or stored_sess or "plan-exec",
                        user_id=owner,
                    )
                except Exception as mark_exc:  # noqa: BLE001
                    logger.warning(
                        "Could not auto-mark task %s done after retry failure: %s",
                        task_id,
                        mark_exc,
                    )

            rec_after = await odb.fetch_plan_record(plan_id)
            rev = int(rec_after.get("revision") or 1) if rec_after else 1
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
        deliverable = infer_deliverable_path(final_md) if final_md else None
        goal = _extract_goal(final_md)

        on_progress({"phase": "writing", "plan_id": plan_id})
        summary = await self._synthesize_final_summary(
            plan_id=plan_id,
            goal=goal,
            plan_markdown=final_md,
            deliverable_path=deliverable,
        )
        on_progress(
            {"phase": "complete", "plan_id": plan_id, "message": "Plan completed"}
        )
        return summary, deliverable

    async def _synthesize_final_summary(
        self,
        *,
        plan_id: str,
        goal: str,
        plan_markdown: str,
        deliverable_path: Optional[str],
    ) -> str:
        from src.research.llm_bridge import complete_messages

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
        )
        if not (text or "").strip():
            return (
                f"✅ Plan `{plan_id}` completato.\n\n"
                f"Deliverable: `{deliverable}`\n\n"
                f"**Goal:** {goal or 'see plan in the Plan panel.'}"
            )
        header = f"## Plan completed — `{plan_id}`\n\n"
        if deliverable:
            header += f"**Deliverable:** `{deliverable}`\n\n"
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
            return False
        entry["_cancel"] = True
        task = entry.get("task")
        if task and not task.done():
            task.cancel()
        future = entry.get("future")
        if future and not future.done():
            future.cancel()
        entry["status"] = "cancelled"
        return True

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
            "Re-approve or restart from the Plan panel."
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

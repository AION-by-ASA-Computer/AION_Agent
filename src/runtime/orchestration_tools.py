"""Tool orchestrazione in-process (draft + progress tracking) con HITL via wait registry."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from src.a2a.plan_markdown import (
    iter_plan_task_rows,
    mark_task_checked,
    markdown_goal,
    markdown_to_plan,
    normalize_plan_task_lines,
    plan_to_markdown,
    plan_to_todos,
    resolve_plan_markdown_for_approval,
    resolve_plan_markdown_lenient,
    todos_to_plan,
)
from src.a2a.protocol import ExecutionPlan
from src.runtime.plan_wait_registry import set_pending
from src.runtime.redis_client import redis_url_for_logs
from src.runtime.tool_events import tool_event_bus

logger = logging.getLogger("aion.orchestration_tools")

# In-process Plan/HITL tools — always merged into every agent (Plan Mode is global).
ORCHESTRATION_BUILTIN_SERVER = "orchestration"
ORCHESTRATION_BUILTIN_TOOL_NAMES: tuple[str, ...] = (
    "draft_execution_plan",
    "list_session_execution_plans",
    "get_execution_plan",
    "update_execution_plan",
    "mark_task_completed",
)


def format_plan_tasks_excerpt(markdown: str, *, max_lines: int = 40) -> str:
    """Compact ## Tasks excerpt for agent system messages."""
    lines = (markdown or "").splitlines()
    out: List[str] = []
    in_tasks = False
    for line in lines:
        low = line.strip().lower()
        if low.startswith("## tasks"):
            in_tasks = True
            out.append(line.strip())
            continue
        if in_tasks and line.strip().startswith("## "):
            break
        if in_tasks:
            out.append(line.rstrip())
        if len(out) >= max_lines:
            out.append("...")
            break
    if out:
        return "\n".join(out)
    rows = iter_plan_task_rows(markdown)
    if not rows:
        return "(no tasks in markdown)"
    return "\n".join(
        f"- [{'x' if done else ' '}] `{tid}` **{title}**"
        for tid, title, done in rows[:max_lines]
    )


def format_plan_progress_summary(rows: List[Tuple[str, str, bool]]) -> str:
    """Human-readable summary: how many steps remain and which ones."""
    total = len(rows)
    if total == 0:
        return (
            "Progress: 0 tasks recognized in plan markdown.\n"
            "Expected per line: `- [ ] `task_01` **Title**` or `- [ ] task_01: Title`.\n"
            "Fix via sidebar Plan editor or update_execution_plan."
        )
    done_rows = [(tid, title) for tid, title, d in rows if d]
    pending_rows = [(tid, title) for tid, title, d in rows if not d]
    lines: List[str] = [
        f"Progress: {len(done_rows)}/{total} tasks completed.",
    ]
    if pending_rows:
        lines.append(f"Remaining steps: {len(pending_rows)} of {total}.")
        lines.append("Pending tasks:")
        for i, (tid, title) in enumerate(pending_rows, 1):
            lines.append(f"  {i}. `{tid}` — {title}")
        lines.append(f"Next to run: `{pending_rows[0][0]}` — {pending_rows[0][1]}")
    else:
        lines.append("Remaining steps: 0 — all plan tasks are completed.")
    if done_rows:
        lines.append(f"Already completed ({len(done_rows)}):")
        for tid, title in done_rows:
            lines.append(f"  - `{tid}` — {title}")
    return "\n".join(lines)


def format_mark_task_result(
    plan_id: str, task_id: str, updated_md: str, revision: int
) -> str:
    from src.runtime.plan_engine import next_pending_task_id

    rows = iter_plan_task_rows(updated_md)
    next_tid = next_pending_task_id(updated_md)
    parts = [
        f"Task `{task_id}` marked completed on plan `{plan_id}` (revision={revision}).",
        format_plan_progress_summary(rows),
        "Source of truth: orchestration DB / sidebar Plan. "
        "Do NOT read workspace/execution_plan_*.md.",
        "STOP this turn now — do not start the next task until the following execution turn.",
    ]
    if next_tid:
        parts.append(f"Next pending task: `{next_tid}`.")
    parts.append(
        f'Full markdown: get_execution_plan(plan_id="{plan_id}"). '
        f'To edit the plan: update_execution_plan(plan_id="{plan_id}", plan_markdown=...).'
    )
    return "\n".join(parts)


async def _persist_plan_markdown(
    plan_id: str,
    markdown: str,
    rec: Dict[str, Any],
    *,
    session_id: str,
    audit_via: str,
    highlight_task_id: str | None = None,
) -> tuple[int, str]:
    """Write markdown to DB, bump revision, notify sidebar. Returns (revision, summary)."""
    from src.runtime import orchestration_db as odb

    parsed = markdown_to_plan(markdown)
    todos = plan_to_todos(parsed)
    revision = int(rec.get("revision") or 1) + 1
    plan_dict = json.loads(parsed.model_dump_json())
    is_approved = bool((rec.get("approved_markdown") or "").strip())
    status = "approved" if is_approved else "draft_pending"
    await odb.update_plan_after_wait(
        plan_id,
        status=status,
        draft_markdown=markdown if not is_approved else None,
        approved_markdown=markdown if is_approved else None,
        approved_json=plan_dict if is_approved else None,
        todos=todos,
        audit_meta={"via": audit_via},
        revision=revision,
    )
    pending_evt = {
        "type": "orchestration_plan_pending",
        "plan_id": plan_id,
        "plan": plan_dict,
        "plan_markdown": markdown,
        "todos": todos,
        "annotations": {},
        "revision": revision,
        "goal": parsed.goal,
        "force_sidebar_refresh": True,
    }
    if highlight_task_id:
        pending_evt["highlight_task_id"] = highlight_task_id
    tool_event_bus.put_event(session_id, pending_evt)
    try:
        from src.runtime.redis_client import redis_enqueue_session_event

        await redis_enqueue_session_event(session_id, pending_evt)
    except Exception as e:
        logger.warning("%s redis_enqueue failed: %s", audit_via, e)
    rows = iter_plan_task_rows(markdown)
    return revision, format_plan_progress_summary(rows)


def _wait_timeout_sec() -> float:
    return float(os.getenv("AION_ORCH_PLAN_WAIT_TIMEOUT_SEC", "600"))


async def resolve_active_plan_id(session_id: str) -> Optional[str]:
    """Preferred plan for the session: most recent approved, else draft_pending."""
    from src.runtime import orchestration_db as odb

    plans = await odb.list_plans_for_session(session_id, limit=20)
    if not plans:
        return None
    for preferred in ("approved", "draft_pending"):
        for row in plans:
            if (row.get("status") or "").strip().lower() == preferred:
                return str(row.get("plan_id") or "").strip() or None
    pid = str(plans[0].get("plan_id") or "").strip()
    return pid or None


async def run_list_session_execution_plans(
    *,
    session_id: str,
    user_id: str,
    limit: int = 10,
) -> str:
    """List orchestration plans for the current chat/session (DB SSOT)."""
    from src.runtime import orchestration_db as odb

    _ = user_id
    plans = await odb.list_plans_for_session(session_id, limit=max(1, min(limit, 20)))
    if not plans:
        return (
            f"No orchestration plan in DB for session `{session_id}`.\n"
            "Plans are not workspace files: do not use sandbox_grep/glob on execution_plan_*.md.\n"
            "Create a plan with `<plan>` in Plan Mode or `draft_execution_plan`."
        )
    active = await resolve_active_plan_id(session_id)
    lines = [
        f"Orchestration plans for session `{session_id}` ({len(plans)}):",
        "Source: DB (sidebar Plan). Do NOT search execution_plan_*.md in workspace.",
    ]
    for row in plans:
        pid = row.get("plan_id", "")
        st = row.get("status", "")
        rev = row.get("revision", 1)
        tag = " ← active plan" if active and pid == active else ""
        lines.append(f"- `{pid}` status={st} revision={rev}{tag}")
    if active:
        lines.append(
            f"\nActive plan (default for mark_task_completed / get_execution_plan without plan_id): `{active}`."
        )
    else:
        lines.append("\nNo resolvable active plan.")
    return "\n".join(lines)


def _parse_plan_markdown_with_fallback(raw: str) -> Tuple[str, ExecutionPlan]:
    """Resolve canonical markdown + plan; never raise (minimal plan as last resort)."""
    body = (raw or "").strip()
    if not body:
        plan = ExecutionPlan.from_goal_and_tasks("Execution plan", None)
        return plan_to_markdown(plan), plan
    return resolve_plan_markdown_lenient(body)


async def setup_execution_plan_from_markdown(
    markdown_content: str,
    *,
    plan_id: str,
    session_id: str,
    user_id: str,
) -> bool:
    """Register pending ExecutionPlan in DB + wait registry. Returns False on hard failure."""
    raw = (markdown_content or "").strip()
    pid = (plan_id or "").strip()
    sid = (session_id or "").strip()
    if not raw or not pid or not sid:
        logger.error(
            "setup_execution_plan: missing data plan=%s session=%s markdown_len=%s",
            pid,
            sid,
            len(raw),
        )
        return False

    markdown_content, plan = _parse_plan_markdown_with_fallback(raw)
    plan_dict = json.loads(plan.model_dump_json())
    from src.a2a.plan_markdown import is_degenerate_plan_json

    if is_degenerate_plan_json(plan_dict):
        logger.error(
            "setup_execution_plan: rejecting degenerate plan (single placeholder task) "
            "plan=%s session=%s — emit structured tasks (task_01, …) or call draft_execution_plan",
            pid,
            sid,
        )
        return False
    todos = plan_to_todos(plan)

    db_ok = False
    try:
        from src.runtime import orchestration_db as odb

        db_ok = await odb.upsert_execution_plan_draft(
            pid,
            sid,
            user_id,
            plan_dict,
            draft_markdown=markdown_content,
            todos=todos,
            status="draft_pending",
        )
    except Exception as e:
        logger.warning("execution_plans DB upsert failed for %s: %s", pid, e)

    if not db_ok:
        logger.error(
            "setup_execution_plan: DB registration failed plan=%s session=%s",
            pid,
            sid,
        )
        return False

    pending_ok = await set_pending(
        pid,
        session_id=sid,
        user_id=user_id,
        draft={
            "plan_markdown": markdown_content,
            "plan_json": plan_dict,
            "todos": todos,
            "annotations": {},
            "revision": 1,
        },
        ttl_sec=max(1, int(_wait_timeout_sec()) + 60),
    )
    if not pending_ok:
        logger.error(
            "HITL: set_pending failed — plan not in orchestration store; "
            "Approve Plan may fail until Redis recovers. redis=%s",
            redis_url_for_logs(),
        )

    tool_event_bus.put_event(
        sid,
        {
            "type": "orchestration_plan_pending",
            "plan_id": pid,
            "plan": plan_dict,
            "plan_markdown": markdown_content,
            "todos": todos,
            "annotations": {},
            "revision": 1,
            "goal": plan.goal,
        },
    )
    return True


async def run_mark_task_completed(
    plan_id: str,
    task_id: str,
    *,
    session_id: str,
    user_id: str,
) -> str:
    from src.runtime import orchestration_db as odb

    _ = user_id
    pid = (plan_id or "").strip()
    if not pid:
        pid = await resolve_active_plan_id(session_id) or ""
    if not pid:
        raise ValueError(
            "No orchestration plan for this session. "
            "Use list_session_execution_plans() — do NOT search execution_plan_*.md in workspace."
        )
    plan_id = pid
    stored = await odb.fetch_plan_session(plan_id)
    if stored and stored != session_id:
        raise ValueError(f"Plan `{plan_id}` does not belong to this session")

    rec = await odb.fetch_plan_record(plan_id)
    if not rec:
        raise ValueError(f"Plan `{plan_id}` not found")

    current_md = (
        rec.get("approved_markdown") or rec.get("draft_markdown") or ""
    ).strip()
    if not current_md:
        raise ValueError(f"Piano `{plan_id}` senza markdown disponibile")

    updated_md = mark_task_checked(current_md, task_id, checked=True)
    from src.runtime.plan_engine import next_pending_task_id

    highlight = next_pending_task_id(updated_md) or task_id
    revision, _summary = await _persist_plan_markdown(
        plan_id,
        updated_md,
        rec,
        session_id=session_id,
        audit_via="single_agent_progress",
        highlight_task_id=highlight,
    )
    return format_mark_task_result(plan_id, task_id, updated_md, revision)


async def run_get_execution_plan(
    plan_id: str | None = None,
    *,
    session_id: str,
    user_id: str,
) -> str:
    """Return canonical plan markdown and task progress from DB (SSOT)."""
    from src.runtime import orchestration_db as odb

    _ = user_id
    pid = (plan_id or "").strip()
    if not pid:
        pid = await resolve_active_plan_id(session_id) or ""
    if not pid:
        return await run_list_session_execution_plans(
            session_id=session_id,
            user_id=user_id,
            limit=10,
        )
    plan_id = pid
    stored = await odb.fetch_plan_session(plan_id)
    if stored and stored != session_id:
        raise ValueError(f"Plan `{plan_id}` does not belong to this session")

    rec = await odb.fetch_plan_record(plan_id)
    if not rec:
        raise ValueError(f"Plan `{plan_id}` not found")

    md = (rec.get("approved_markdown") or rec.get("draft_markdown") or "").strip()
    if not md:
        raise ValueError(f"Plan `{plan_id}` has no markdown")

    rows = iter_plan_task_rows(md)
    st = "approved" if rec.get("approved_markdown") else "draft_pending"
    revision = int(rec.get("revision") or 1)

    header = (
        f"Plan `{plan_id}` (status={st}, revision={revision}). Source: orchestration DB.\n\n"
        f"{format_plan_progress_summary(rows)}\n\n"
        "To change goal/context/tasks send the full updated markdown via "
        f'update_execution_plan(plan_id="{plan_id}", plan_markdown=...).\n\n'
        "--- Markdown ---\n\n"
    )

    body = md if len(md) <= 12000 else md[:12000] + "\n\n...(markdown truncated)"
    return header + body


async def run_update_execution_plan(
    plan_id: str,
    plan_markdown: str,
    *,
    session_id: str,
    user_id: str,
) -> str:
    """Replace plan markdown in DB (sidebar SSOT). Use after failures or scope changes."""
    from src.runtime import orchestration_db as odb

    _ = user_id
    stored = await odb.fetch_plan_session(plan_id)
    if stored and stored != session_id:
        raise ValueError(f"Plan `{plan_id}` does not belong to this session")

    rec = await odb.fetch_plan_record(plan_id)
    if not rec:
        raise ValueError(f"Plan `{plan_id}` not found")

    md = normalize_plan_task_lines((plan_markdown or "").strip())
    if not md:
        raise ValueError("plan_markdown is required")

    try:
        markdown_to_plan(md)
    except Exception as e:
        raise ValueError(f"Invalid plan markdown: {e}") from e

    revision, summary = await _persist_plan_markdown(
        plan_id,
        md,
        rec,
        session_id=session_id,
        audit_via="agent_update_execution_plan",
    )
    return (
        f"Plan `{plan_id}` updated in DB (revision={revision}).\n"
        f"{summary}\n\n"
        "Sidebar Plan shows the new markdown. "
        "Continue with mark_task_completed after each completed step."
    )


async def run_draft_execution_plan(
    goal: str,
    tasks: str | list | None = None,
    *,
    session_id: str,
    user_id: str,
    plan_id: str | None = None,
) -> str:
    """Create HITL plan in sidebar (primary path in Plan Mode tool-first)."""
    from src.runtime.context import get_context
    from src.runtime.plan_coercion import new_execution_plan_id

    g = (goal or "").strip()
    if not g:
        raise ValueError("goal is required")
    if tasks is None:
        raise ValueError(
            "tasks is required: JSON array with at least 2 atomic tasks "
            "(ids task_01, task_02, …; each title = one concrete action)"
        )
    if isinstance(tasks, str) and not tasks.strip():
        raise ValueError("tasks must be a non-empty JSON array of task objects")
    if isinstance(tasks, list) and len(tasks) < 2:
        raise ValueError(
            f"tasks must include at least 2 atomic steps (got {len(tasks)}); "
            "split milestones into task_01, task_02, …"
        )

    plan = ExecutionPlan.from_goal_and_tasks(g, tasks)
    plan_dict_probe = json.loads(plan.model_dump_json())
    from src.a2a.plan_markdown import is_degenerate_plan_json

    if is_degenerate_plan_json(plan_dict_probe):
        raise ValueError(
            "degenerate plan: provide structured tasks (task_01, task_02, …), "
            "not a single catch-all step"
        )
    ctx = get_context()
    resolved_pid = (
        (plan_id or "").strip()
        or str(ctx.get("turn_plan_id") or "").strip()
        or new_execution_plan_id()
    )
    markdown = plan_to_markdown(plan)
    await setup_execution_plan_from_markdown(
        markdown,
        plan_id=resolved_pid,
        session_id=session_id,
        user_id=user_id,
    )
    try:
        from src.runtime.redis_client import redis_enqueue_session_event

        plan_dict = json.loads(plan.model_dump_json())
        todos = plan_to_todos(plan)
        await redis_enqueue_session_event(
            session_id,
            {
                "type": "orchestration_plan_pending",
                "plan_id": resolved_pid,
                "plan": plan_dict,
                "plan_markdown": markdown,
                "todos": todos,
                "annotations": {},
                "revision": 1,
                "goal": plan.goal,
                "force_sidebar_refresh": True,
            },
        )
    except Exception as exc:
        logger.warning("draft_execution_plan redis_enqueue failed: %s", exc)
    return (
        f"Plan `{resolved_pid}` created pending approval ({len(plan.tasks)} tasks). "
        "User must approve from the sidebar Plan before execution."
    )


def merge_builtin_orchestration_tools(
    tools: List[Any], session_id: str, user_id: str
) -> List[Any]:
    """Append orchestration in-process tools unless already present (dedupe by name)."""
    existing = {getattr(t, "name", None) for t in tools}
    for haystack_tool in build_orchestration_haystack_tools(session_id, user_id):
        name = getattr(haystack_tool, "name", None)
        if name and name not in existing:
            tools.append(haystack_tool)
            existing.add(name)
    return tools


def _instrument_orchestration_tool(session_id: str, tool_name: str, fn):
    """Emit tool_start / tool_end / tool_error on the SSE bus (same as native MCP tools)."""

    def wrapped(**kwargs):
        from src.runtime.native_tool_events import (
            emit_tool_end,
            emit_tool_error,
            emit_tool_start,
        )

        inp = {k: v for k, v in kwargs.items() if v is not None}
        call_id = emit_tool_start(session_id, tool_name, inp)
        try:
            result = fn(**kwargs)
            body = str(result) if result is not None else ""
            emit_tool_end(session_id, tool_name, call_id, body[:24000])
            return result
        except Exception as exc:
            emit_tool_error(session_id, tool_name, call_id, str(exc))
            raise

    wrapped.__name__ = getattr(fn, "__name__", tool_name)
    return wrapped


def build_orchestration_haystack_tools(session_id: str, user_id: str) -> List[Any]:
    from haystack.tools import Tool

    def _run_async(coro) -> str:
        import asyncio

        from src.main import _GLOBAL_LOOP

        loop = _GLOBAL_LOOP
        if not loop:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                pass
        if not loop:
            raise RuntimeError("No event loop for orchestration tools")
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=float(os.getenv("AION_ORCH_TOOL_TIMEOUT_SEC", "900")))

    def draft_execution_plan_fn(goal: str, tasks: str | list | None = None) -> str:
        return _run_async(
            run_draft_execution_plan(
                goal, tasks, session_id=session_id, user_id=user_id
            )
        )

    def list_session_execution_plans_fn(limit: int = 10) -> str:
        return _run_async(
            run_list_session_execution_plans(
                session_id=session_id,
                user_id=user_id,
                limit=limit,
            )
        )

    def get_execution_plan_fn(plan_id: str | None = None) -> str:
        return _run_async(
            run_get_execution_plan(plan_id, session_id=session_id, user_id=user_id)
        )

    def update_execution_plan_fn(plan_id: str, plan_markdown: str) -> str:
        return _run_async(
            run_update_execution_plan(
                plan_id,
                plan_markdown,
                session_id=session_id,
                user_id=user_id,
            )
        )

    def mark_task_completed_fn(plan_id: str | None = None, task_id: str = "") -> str:
        # Guard: only one successful mark_task_completed per agent turn.
        # Failed marks do not consume the slot (agent can fix task_id and retry).
        from src.runtime.context import get_context

        ctx = get_context()
        mark_once = ctx.get("mark_once")

        def _raise_if_already_used() -> None:
            if mark_once is None:
                return
            lock = mark_once.get("lock")
            if lock is not None:
                with lock:
                    if mark_once.get("used"):
                        raise RuntimeError(
                            "mark_task_completed was already called once in this turn. "
                            "STOP — do not call it again. Wait for the next execution turn."
                        )
            elif mark_once.get("used"):
                raise RuntimeError(
                    "mark_task_completed was already called once in this turn. "
                    "STOP — do not call it again. Wait for the next execution turn."
                )

        def _mark_used() -> None:
            if mark_once is None:
                return
            lock = mark_once.get("lock")
            if lock is not None:
                with lock:
                    mark_once["used"] = True
            else:
                mark_once["used"] = True

        _raise_if_already_used()
        try:
            result = _run_async(
                run_mark_task_completed(
                    plan_id or "",
                    task_id,
                    session_id=session_id,
                    user_id=user_id,
                )
            )
        except Exception:
            raise
        else:
            _mark_used()
            return result

    def _orch_tool(name: str, description: str, fn, parameters: dict) -> Any:
        return Tool(
            name=name,
            description=description,
            function=_instrument_orchestration_tool(session_id, name, fn),
            parameters=parameters,
        )

    return [
        _orch_tool(
            "list_session_execution_plans",
            (
                "List orchestration plans for the current session (id, status, revision). "
                "Call BEFORE mark_task_completed if plan_id is unknown. "
                "Plans live in DB/sidebar only — do NOT sandbox_fnmatch_glob execution_plan_*.md."
            ),
            list_session_execution_plans_fn,
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max plans to list (default 10)",
                    },
                },
            },
        ),
        _orch_tool(
            "get_execution_plan",
            (
                "Read plan from DB (checkboxes and tasks). Optional plan_id: if omitted uses the "
                "active session plan (most recent approved). "
                "Do NOT read workspace/execution_plan_*.md."
            ),
            get_execution_plan_fn,
            parameters={
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "string",
                        "description": "Sidebar id (e.g. execution_plan_7f2c55). Empty = active session plan.",
                    },
                },
            },
        ),
        _orch_tool(
            "update_execution_plan",
            (
                "Replace plan markdown in DB (Goal/Context/Tasks/Notes). "
                "Use to add remediation tasks, fix deps, or update context without workspace files. "
                "Send the full updated plan in plan_markdown."
            ),
            update_execution_plan_fn,
            parameters={
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "string",
                        "description": "Sidebar id, e.g. execution_plan_7f2c55",
                    },
                    "plan_markdown": {
                        "type": "string",
                        "description": "Full markdown with ## Goal, ## Tasks, checkboxes - [ ] / - [x]",
                    },
                },
                "required": ["plan_id", "plan_markdown"],
            },
        ),
        _orch_tool(
            "draft_execution_plan",
            (
                "Create execution plan in sidebar (HITL) from goal and structured tasks. "
                "Prefer `<plan>` tag in Plan Mode; use this tool only when a plan must be created via tool call. "
                "Wait for user approval before mutating tasks."
            ),
            draft_execution_plan_fn,
            parameters={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "Verifiable plan objective",
                    },
                    "tasks": {
                        "type": "string",
                        "description": "JSON task array or task markdown lines (optional)",
                    },
                },
                "required": ["goal"],
            },
        ),
        _orch_tool(
            "mark_task_completed",
            (
                "Mark a task completed (checkbox `- [x]` in DB/sidebar). "
                "Optional plan_id: if omitted uses active session plan. "
                "Call list_session_execution_plans or get_execution_plan first if unsure. "
                "task_id: e.g. task_01 from ## Tasks."
            ),
            mark_task_completed_fn,
            parameters={
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "string",
                        "description": "Sidebar id. Empty = active approved session plan.",
                    },
                    "task_id": {"type": "string"},
                },
                "required": ["task_id"],
            },
        ),
    ]

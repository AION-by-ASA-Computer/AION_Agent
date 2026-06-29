"""Built-in Haystack tools for per-user scheduled jobs."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from src.runtime import cron_db
from src.runtime.cron_runner import execute_job
from src.runtime.cron_scheduler import register_job, reschedule_job, unregister_job

logger = logging.getLogger("aion.cron_tools")

CRON_BUILTIN_SERVER = "cron"
CRON_BUILTIN_TOOL_NAMES: tuple[str, ...] = (
    "create_scheduled_job",
    "list_scheduled_jobs",
    "get_scheduled_job",
    "update_scheduled_job",
    "delete_scheduled_job",
    "pause_scheduled_job",
    "resume_scheduled_job",
    "run_scheduled_job_now",
)


def _max_jobs_per_user() -> int:
    try:
        return max(1, int(os.getenv("AION_CRON_MAX_JOBS_PER_USER", "50")))
    except ValueError:
        return 50


def cron_tools_enabled() -> bool:
    return os.environ.get("AION_CRON_ENABLED", "0").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _disabled_msg() -> str:
    return "Scheduled jobs are disabled (set AION_CRON_ENABLED=1 on the server)."


async def _create_scheduled_job(
    name: str,
    cron_expression: str,
    prompt: str,
    *,
    session_id: str,
    user_id: str,
    profile_slug: Optional[str] = None,
    session_mode: str = "fixed",
    timezone: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    if not cron_tools_enabled():
        return _disabled_msg()
    n = await cron_db.count_jobs_for_user(user_id)
    if n >= _max_jobs_per_user():
        return f"Error: max scheduled jobs per user ({_max_jobs_per_user()}) reached."
    job = await cron_db.create_job(
        user_id=user_id,
        name=name,
        cron_expression=cron_expression,
        prompt=prompt,
        profile_slug=profile_slug or "generic_assistant",
        session_mode=session_mode,
        session_id=session_id if session_mode == "fixed" else None,
        timezone=timezone,
        description=description,
        enabled=True,
        created_by="agent",
    )
    await register_job(job["job_id"])
    return (
        f"Created scheduled job `{job['job_id']}` ({job['name']}). "
        f"Cron: `{job['cron_expression']}` ({job['timezone']}). "
        f"Next run: {job.get('next_run_at') or 'n/a'}. "
        f"Session mode: {job['session_mode']}."
    )


async def _list_scheduled_jobs(session_id: str, user_id: str) -> str:
    if not cron_tools_enabled():
        return _disabled_msg()
    jobs = await cron_db.list_jobs(user_id=user_id, limit=50)
    if not jobs:
        return "No scheduled jobs for this user."
    lines = [f"Found {len(jobs)} scheduled job(s):"]
    for j in jobs:
        st = "enabled" if j.get("enabled") else "paused"
        lr = j.get("last_run") or {}
        lr_st = lr.get("status") or "-"
        lines.append(
            f"- `{j['job_id']}` **{j['name']}** [{st}] cron=`{j['cron_expression']}` "
            f"next={j.get('next_run_at') or '-'} last_run={lr_st}"
        )
    return "\n".join(lines)


async def _get_scheduled_job(job_id: str, user_id: str) -> str:
    if not cron_tools_enabled():
        return _disabled_msg()
    job = await cron_db.get_job(job_id)
    if not job:
        return f"Job `{job_id}` not found."
    if job.get("user_id") != user_id:
        return "Error: job belongs to another user."
    import json

    return json.dumps(job, ensure_ascii=False, indent=2)


async def _update_scheduled_job(
    job_id: str,
    user_id: str,
    *,
    name: Optional[str] = None,
    cron_expression: Optional[str] = None,
    prompt: Optional[str] = None,
    profile_slug: Optional[str] = None,
    session_mode: Optional[str] = None,
    timezone: Optional[str] = None,
    description: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> str:
    if not cron_tools_enabled():
        return _disabled_msg()
    existing = await cron_db.get_job(job_id)
    if not existing:
        return f"Job `{job_id}` not found."
    if existing.get("user_id") != user_id:
        return "Error: job belongs to another user."
    patch: Dict[str, Any] = {}
    if name is not None:
        patch["name"] = name
    if cron_expression is not None:
        patch["cron_expression"] = cron_expression
    if prompt is not None:
        patch["prompt"] = prompt
    if profile_slug is not None:
        patch["profile_slug"] = profile_slug
    if session_mode is not None:
        patch["session_mode"] = session_mode
    if timezone is not None:
        patch["timezone"] = timezone
    if description is not None:
        patch["description"] = description
    if enabled is not None:
        patch["enabled"] = enabled
    updated = await cron_db.update_job(job_id, patch=patch)
    if not updated:
        return f"Failed to update `{job_id}`."
    await reschedule_job(job_id)
    return f"Updated job `{job_id}`. Next run: {updated.get('next_run_at') or 'n/a'}."


async def _delete_scheduled_job(job_id: str, user_id: str) -> str:
    if not cron_tools_enabled():
        return _disabled_msg()
    existing = await cron_db.get_job(job_id)
    if not existing:
        return f"Job `{job_id}` not found."
    if existing.get("user_id") != user_id:
        return "Error: job belongs to another user."
    await unregister_job(job_id)
    await cron_db.delete_job(job_id)
    return f"Deleted scheduled job `{job_id}`."


async def _pause_scheduled_job(job_id: str, user_id: str) -> str:
    return await _update_scheduled_job(job_id, user_id, enabled=False)


async def _resume_scheduled_job(job_id: str, user_id: str) -> str:
    return await _update_scheduled_job(job_id, user_id, enabled=True)


async def _run_scheduled_job_now(job_id: str, user_id: str) -> str:
    if not cron_tools_enabled():
        return _disabled_msg()
    existing = await cron_db.get_job(job_id)
    if not existing:
        return f"Job `{job_id}` not found."
    if existing.get("user_id") != user_id:
        return "Error: job belongs to another user."
    result = await execute_job(job_id, trigger="agent")
    import json

    return json.dumps(result, ensure_ascii=False, indent=2)


def merge_builtin_cron_tools(
    tools: List[Any], session_id: str, user_id: str
) -> List[Any]:
    if not cron_tools_enabled():
        return tools
    existing = {getattr(t, "name", None) for t in tools}
    for haystack_tool in build_cron_haystack_tools(session_id, user_id):
        name = getattr(haystack_tool, "name", None)
        if name and name not in existing:
            tools.append(haystack_tool)
            existing.add(name)
    return tools


def build_cron_haystack_tools(session_id: str, user_id: str) -> List[Any]:
    from haystack.tools import Tool

    def _run_async(coro) -> str:
        from src.main import _GLOBAL_LOOP

        loop = _GLOBAL_LOOP
        if not loop:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                pass
        if not loop:
            raise RuntimeError("No event loop for cron tools")
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=float(os.getenv("AION_CRON_TOOL_TIMEOUT_SEC", "120")))

    def create_scheduled_job_fn(
        name: str,
        cron_expression: str,
        prompt: str,
        profile_slug: Optional[str] = None,
        session_mode: str = "fixed",
        timezone: Optional[str] = None,
        description: Optional[str] = None,
    ) -> str:
        return _run_async(
            _create_scheduled_job(
                name,
                cron_expression,
                prompt,
                session_id=session_id,
                user_id=user_id,
                profile_slug=profile_slug,
                session_mode=session_mode,
                timezone=timezone,
                description=description,
            )
        )

    def list_scheduled_jobs_fn() -> str:
        return _run_async(_list_scheduled_jobs(session_id, user_id))

    def get_scheduled_job_fn(job_id: str) -> str:
        return _run_async(_get_scheduled_job(job_id, user_id))

    def update_scheduled_job_fn(
        job_id: str,
        name: Optional[str] = None,
        cron_expression: Optional[str] = None,
        prompt: Optional[str] = None,
        profile_slug: Optional[str] = None,
        session_mode: Optional[str] = None,
        timezone: Optional[str] = None,
        description: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> str:
        return _run_async(
            _update_scheduled_job(
                job_id,
                user_id,
                name=name,
                cron_expression=cron_expression,
                prompt=prompt,
                profile_slug=profile_slug,
                session_mode=session_mode,
                timezone=timezone,
                description=description,
                enabled=enabled,
            )
        )

    def delete_scheduled_job_fn(job_id: str) -> str:
        return _run_async(_delete_scheduled_job(job_id, user_id))

    def pause_scheduled_job_fn(job_id: str) -> str:
        return _run_async(_pause_scheduled_job(job_id, user_id))

    def resume_scheduled_job_fn(job_id: str) -> str:
        return _run_async(_resume_scheduled_job(job_id, user_id))

    def run_scheduled_job_now_fn(job_id: str) -> str:
        return _run_async(_run_scheduled_job_now(job_id, user_id))

    return [
        Tool(
            name="create_scheduled_job",
            description=(
                "Create a recurring scheduled task for the current user. "
                "Uses standard 5-field cron (minute hour day month weekday). "
                "session_mode: 'fixed' reuses one conversation; 'new' starts fresh each run."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "cron_expression": {
                        "type": "string",
                        "description": "e.g. 0 9 * * 1",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Message sent to the agent each run",
                    },
                    "profile_slug": {"type": "string"},
                    "session_mode": {"type": "string", "enum": ["fixed", "new"]},
                    "timezone": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "cron_expression", "prompt"],
            },
            function=create_scheduled_job_fn,
        ),
        Tool(
            name="list_scheduled_jobs",
            description="List scheduled jobs for the current user.",
            parameters={"type": "object", "properties": {}},
            function=list_scheduled_jobs_fn,
        ),
        Tool(
            name="get_scheduled_job",
            description="Get details of one scheduled job (must belong to current user).",
            parameters={
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
            function=get_scheduled_job_fn,
        ),
        Tool(
            name="update_scheduled_job",
            description="Update fields of a scheduled job.",
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "name": {"type": "string"},
                    "cron_expression": {"type": "string"},
                    "prompt": {"type": "string"},
                    "profile_slug": {"type": "string"},
                    "session_mode": {"type": "string"},
                    "timezone": {"type": "string"},
                    "description": {"type": "string"},
                    "enabled": {"type": "boolean"},
                },
                "required": ["job_id"],
            },
            function=update_scheduled_job_fn,
        ),
        Tool(
            name="delete_scheduled_job",
            description="Delete a scheduled job permanently.",
            parameters={
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
            function=delete_scheduled_job_fn,
        ),
        Tool(
            name="pause_scheduled_job",
            description="Disable a scheduled job without deleting it.",
            parameters={
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
            function=pause_scheduled_job_fn,
        ),
        Tool(
            name="resume_scheduled_job",
            description="Re-enable a paused scheduled job.",
            parameters={
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
            function=resume_scheduled_job_fn,
        ),
        Tool(
            name="run_scheduled_job_now",
            description="Run a scheduled job immediately (manual trigger).",
            parameters={
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
            function=run_scheduled_job_now_fn,
        ),
    ]

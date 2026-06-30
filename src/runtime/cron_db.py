"""CRUD for scheduled_jobs / scheduled_job_runs."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, select, update

from src.data.engine import get_async_session_maker
from src.data.models import ScheduledJob, ScheduledJobRun
from src.runtime.cron_expression import (
    compute_next_run_at,
    validate_cron_expression,
    validate_session_mode,
    default_timezone,
)

RUN_STATUSES = frozenset({"running", "success", "error", "skipped"})


def _tenant_id() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"


def _job_to_dict(
    row: ScheduledJob, *, last_run: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    if row.metadata_json:
        try:
            meta = json.loads(row.metadata_json) or {}
        except Exception:
            meta = {}
    return {
        "job_id": row.job_id,
        "tenant_id": row.tenant_id,
        "user_id": row.user_id,
        "name": row.name,
        "description": row.description,
        "cron_expression": row.cron_expression,
        "timezone": row.timezone,
        "profile_slug": row.profile_slug,
        "prompt": row.prompt,
        "session_mode": row.session_mode,
        "session_id": row.session_id,
        "enabled": bool(row.enabled),
        "agent_mode": row.agent_mode,
        "metadata": meta,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
        "last_run": last_run,
    }


def _run_to_dict(row: ScheduledJobRun) -> Dict[str, Any]:
    return {
        "run_id": row.run_id,
        "job_id": row.job_id,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "status": row.status,
        "session_id": row.session_id,
        "conversation_id": row.conversation_id,
        "error_message": row.error_message,
        "assistant_preview": row.assistant_preview,
    }


async def count_jobs_for_user(user_id: str, *, tenant_id: Optional[str] = None) -> int:
    tid = tenant_id or _tenant_id()
    maker = get_async_session_maker()
    async with maker() as session:
        r = await session.execute(
            select(func.count())
            .select_from(ScheduledJob)
            .where(ScheduledJob.user_id == user_id, ScheduledJob.tenant_id == tid)
        )
        return int(r.scalar() or 0)


async def create_job(
    *,
    user_id: str,
    name: str,
    cron_expression: str,
    prompt: str,
    profile_slug: str,
    session_mode: str = "fixed",
    session_id: Optional[str] = None,
    timezone: Optional[str] = None,
    description: Optional[str] = None,
    enabled: bool = True,
    agent_mode: str = "normal",
    created_by: str = "user",
    metadata: Optional[Dict[str, Any]] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    tid = tenant_id or _tenant_id()
    tz = (timezone or default_timezone()).strip() or "UTC"
    expr = validate_cron_expression(cron_expression, tz)
    smode = validate_session_mode(session_mode)
    job_id = str(uuid.uuid4())
    nxt = compute_next_run_at(expr, tz) if enabled else None
    row = ScheduledJob(
        job_id=job_id,
        tenant_id=tid,
        user_id=user_id,
        name=(name or "").strip() or "Scheduled job",
        description=(description or "").strip() or None,
        cron_expression=expr,
        timezone=tz,
        profile_slug=(profile_slug or "generic_assistant").strip(),
        prompt=(prompt or "").strip(),
        session_mode=smode,
        session_id=(session_id or "").strip() or None,
        enabled=bool(enabled),
        agent_mode=(agent_mode or "normal").strip().lower() or "normal",
        metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
        created_by=(created_by or "user").strip() or "user",
        next_run_at=nxt,
    )
    if not row.prompt:
        raise ValueError("prompt is required")
    maker = get_async_session_maker()
    async with maker() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return _job_to_dict(row)


async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    maker = get_async_session_maker()
    async with maker() as session:
        row = await session.get(ScheduledJob, job_id)
        if not row:
            return None
        lr = await _fetch_last_run(session, job_id)
    return _job_to_dict(row, last_run=lr)


async def _fetch_last_run(session, job_id: str) -> Optional[Dict[str, Any]]:
    r = await session.execute(
        select(ScheduledJobRun)
        .where(ScheduledJobRun.job_id == job_id)
        .order_by(ScheduledJobRun.started_at.desc())
        .limit(1)
    )
    run = r.scalars().first()
    return _run_to_dict(run) if run else None


async def list_jobs(
    *,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    enabled: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    maker = get_async_session_maker()
    async with maker() as session:
        q = select(ScheduledJob).order_by(ScheduledJob.created_at.desc())
        if user_id:
            q = q.where(ScheduledJob.user_id == user_id)
        if tenant_id:
            q = q.where(ScheduledJob.tenant_id == tenant_id)
        if enabled is not None:
            q = q.where(ScheduledJob.enabled.is_(enabled))
        q = q.offset(max(0, offset)).limit(max(1, min(limit, 500)))
        rows = (await session.execute(q)).scalars().all()
        out: List[Dict[str, Any]] = []
        for row in rows:
            lr = await _fetch_last_run(session, row.job_id)
            out.append(_job_to_dict(row, last_run=lr))
    return out


async def list_enabled_jobs() -> List[Dict[str, Any]]:
    return await list_jobs(enabled=True, limit=500)


async def update_job(
    job_id: str,
    *,
    patch: Dict[str, Any],
    recompute_next: bool = True,
) -> Optional[Dict[str, Any]]:
    maker = get_async_session_maker()
    async with maker() as session:
        row = await session.get(ScheduledJob, job_id)
        if not row:
            return None
        if "name" in patch and patch["name"] is not None:
            row.name = str(patch["name"]).strip() or row.name
        if "description" in patch:
            row.description = (
                str(patch["description"]).strip() if patch["description"] else None
            )
        if "cron_expression" in patch and patch["cron_expression"] is not None:
            row.cron_expression = validate_cron_expression(
                str(patch["cron_expression"]), row.timezone
            )
        if "timezone" in patch and patch["timezone"] is not None:
            row.timezone = str(patch["timezone"]).strip() or row.timezone
            row.cron_expression = validate_cron_expression(
                row.cron_expression, row.timezone
            )
        if "profile_slug" in patch and patch["profile_slug"] is not None:
            row.profile_slug = str(patch["profile_slug"]).strip()
        if "prompt" in patch and patch["prompt"] is not None:
            p = str(patch["prompt"]).strip()
            if p:
                row.prompt = p
        if "session_mode" in patch and patch["session_mode"] is not None:
            row.session_mode = validate_session_mode(str(patch["session_mode"]))
        if "session_id" in patch:
            sid = patch["session_id"]
            row.session_id = str(sid).strip() if sid else None
        if "enabled" in patch and patch["enabled"] is not None:
            row.enabled = bool(patch["enabled"])
        if "agent_mode" in patch and patch["agent_mode"] is not None:
            row.agent_mode = str(patch["agent_mode"]).strip().lower() or "normal"
        if "metadata" in patch and patch["metadata"] is not None:
            row.metadata_json = json.dumps(patch["metadata"], ensure_ascii=False)
        if recompute_next:
            row.next_run_at = (
                compute_next_run_at(row.cron_expression, row.timezone)
                if row.enabled
                else None
            )
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(row)
        lr = await _fetch_last_run(session, job_id)
    return _job_to_dict(row, last_run=lr)


async def set_job_session_id(job_id: str, session_id: str) -> None:
    maker = get_async_session_maker()
    async with maker() as session:
        await session.execute(
            update(ScheduledJob)
            .where(ScheduledJob.job_id == job_id)
            .values(session_id=session_id, updated_at=datetime.now(timezone.utc))
        )
        await session.commit()


async def delete_job(job_id: str) -> bool:
    maker = get_async_session_maker()
    async with maker() as session:
        row = await session.get(ScheduledJob, job_id)
        if not row:
            return False
        await session.delete(row)
        await session.commit()
    return True


async def insert_run_start(
    job_id: str,
    *,
    session_id: str,
    conversation_id: str,
) -> str:
    run_id = str(uuid.uuid4())
    maker = get_async_session_maker()
    async with maker() as session:
        session.add(
            ScheduledJobRun(
                run_id=run_id,
                job_id=job_id,
                started_at=datetime.now(timezone.utc),
                status="running",
                session_id=session_id,
                conversation_id=conversation_id,
            )
        )
        await session.commit()
    return run_id


async def finish_run(
    run_id: str,
    *,
    status: str,
    error_message: Optional[str] = None,
    assistant_preview: Optional[str] = None,
) -> None:
    st = (status or "error").strip().lower()
    if st not in RUN_STATUSES:
        st = "error"
    maker = get_async_session_maker()
    async with maker() as session:
        await session.execute(
            update(ScheduledJobRun)
            .where(ScheduledJobRun.run_id == run_id)
            .values(
                status=st,
                finished_at=datetime.now(timezone.utc),
                error_message=error_message,
                assistant_preview=assistant_preview,
            )
        )
        await session.commit()


async def has_running_run(job_id: str) -> bool:
    maker = get_async_session_maker()
    async with maker() as session:
        r = await session.execute(
            select(func.count())
            .select_from(ScheduledJobRun)
            .where(
                ScheduledJobRun.job_id == job_id, ScheduledJobRun.status == "running"
            )
        )
        return int(r.scalar() or 0) > 0


async def list_runs(job_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    maker = get_async_session_maker()
    async with maker() as session:
        r = await session.execute(
            select(ScheduledJobRun)
            .where(ScheduledJobRun.job_id == job_id)
            .order_by(ScheduledJobRun.started_at.desc())
            .limit(max(1, min(limit, 200)))
        )
        return [_run_to_dict(x) for x in r.scalars().all()]


async def bump_next_run_after_fire(job_id: str) -> None:
    maker = get_async_session_maker()
    async with maker() as session:
        row = await session.get(ScheduledJob, job_id)
        if not row or not row.enabled:
            return
        row.next_run_at = compute_next_run_at(row.cron_expression, row.timezone)
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()


async def cleanup_orphaned_runs() -> None:
    maker = get_async_session_maker()
    async with maker() as session:
        await session.execute(
            update(ScheduledJobRun)
            .where(ScheduledJobRun.status == "running")
            .values(
                status="error",
                finished_at=datetime.now(timezone.utc),
                error_message="Orphaned run reset at startup",
            )
        )
        await session.commit()
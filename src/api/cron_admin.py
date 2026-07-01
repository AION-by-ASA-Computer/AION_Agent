"""Admin CRUD for all users' scheduled jobs."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.auth_login import require_admin_role
from src.api.cron_schemas import (
    ScheduledJobCreate,
    ScheduledJobListResponse,
    ScheduledJobOut,
    ScheduledJobUpdate,
    ScheduledRunListResponse,
    ScheduledRunOut,
)
from src.identity import sanitize_user_id
from src.runtime import cron_db
from src.runtime.cron_runner import execute_job
from src.runtime.cron_scheduler import register_job, reschedule_job, unregister_job
from src.runtime.cron_tools import cron_tools_enabled

router = APIRouter(prefix="/cron-jobs", tags=["admin-cron"])


class AdminScheduledJobCreate(ScheduledJobCreate):
    user_id: str


def _require_cron() -> None:
    if not cron_tools_enabled():
        raise HTTPException(
            status_code=503, detail="Cron disabled (AION_CRON_ENABLED=0)"
        )


def _out(d: dict) -> ScheduledJobOut:
    return ScheduledJobOut(**d)


@router.get("", response_model=ScheduledJobListResponse)
async def list_cron_jobs(
    user_id: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin=Depends(require_admin_role),
):
    _require_cron()
    tid = tenant_id or (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()
    jobs = await cron_db.list_jobs(
        user_id=sanitize_user_id(user_id) if user_id else None,
        tenant_id=tid if tenant_id else None,
        enabled=enabled,
        limit=limit,
        offset=offset,
    )
    return ScheduledJobListResponse(jobs=[_out(j) for j in jobs], total=len(jobs))


@router.get("/{job_id}", response_model=ScheduledJobOut)
async def get_cron_job(job_id: str, _admin=Depends(require_admin_role)):
    _require_cron()
    job = await cron_db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _out(job)


@router.post("", response_model=ScheduledJobOut)
async def create_cron_job(
    body: AdminScheduledJobCreate, _admin=Depends(require_admin_role)
):
    _require_cron()
    uid = sanitize_user_id(body.user_id.strip() if body.user_id else None)
    if not uid:
        raise HTTPException(status_code=400, detail="user_id is required")
    try:
        job = await cron_db.create_job(
            user_id=uid,
            name=body.name,
            cron_expression=body.cron_expression,
            prompt=body.prompt,
            profile_slug=body.profile_slug,
            session_mode=body.session_mode,
            session_id=body.session_id,
            timezone=body.timezone,
            description=body.description,
            enabled=body.enabled,
            agent_mode=body.agent_mode,
            created_by="admin",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if job.get("enabled"):
        await register_job(job["job_id"])
    return _out(job)


@router.patch("/{job_id}", response_model=ScheduledJobOut)
async def patch_cron_job(
    job_id: str,
    body: ScheduledJobUpdate,
    _admin=Depends(require_admin_role),
):
    _require_cron()
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        job = await cron_db.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return _out(job)
    try:
        updated = await cron_db.update_job(job_id, patch=patch)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not updated:
        raise HTTPException(status_code=404, detail="Job not found")
    await reschedule_job(job_id)
    return _out(updated)


@router.delete("/{job_id}")
async def delete_cron_job(job_id: str, _admin=Depends(require_admin_role)):
    _require_cron()
    await unregister_job(job_id)
    ok = await cron_db.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "job_id": job_id}


@router.post("/{job_id}/run-now")
async def run_cron_job_now(
    job_id: str,
    background_tasks: BackgroundTasks,
    _admin=Depends(require_admin_role),
):
    _require_cron()
    job = await cron_db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    background_tasks.add_task(execute_job, job_id, trigger="admin")
    return {"ok": True, "job_id": job_id, "status": "running"}


@router.get("/{job_id}/runs", response_model=ScheduledRunListResponse)
async def list_cron_job_runs(
    job_id: str,
    limit: int = Query(50, ge=1, le=200),
    _admin=Depends(require_admin_role),
):
    _require_cron()
    job = await cron_db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    runs = await cron_db.list_runs(job_id, limit=limit)
    return ScheduledRunListResponse(runs=[ScheduledRunOut(**r) for r in runs])

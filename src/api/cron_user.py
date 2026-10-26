"""User-facing scheduled jobs API (chat JWT)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.api.cron_schemas import (
    ScheduledJobCreate,
    ScheduledJobListResponse,
    ScheduledJobOut,
    ScheduledJobUpdate,
    ScheduledRunListResponse,
    ScheduledRunOut,
)
from src.api.ownership import assert_conversation_access, effective_user_id
from src.session_workspace import normalize_session_id
from src.runtime import cron_db
from src.runtime.cron_runner import execute_job
from src.runtime.cron_scheduler import register_job, reschedule_job, unregister_job
from src.runtime.cron_tools import _max_jobs_per_user, cron_tools_enabled

router = APIRouter(prefix="/cron-jobs", tags=["cron-jobs"])


@router.get("/status")
async def cron_jobs_status() -> dict:
    """Public check for chat-ui (no auth): whether scheduled jobs are enabled on this server."""
    enabled = cron_tools_enabled()
    return {
        "cron_enabled": enabled,
        "hint": (
            None
            if enabled
            else "Imposta AION_CRON_ENABLED=1 nel .env del backend e riavvia l'API (uvicorn)."
        ),
    }


def _require_cron() -> None:
    if not cron_tools_enabled():
        raise HTTPException(
            status_code=503, detail="Cron disabled (AION_CRON_ENABLED=0)"
        )


async def _cron_user_id(
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> str:
    if auth.via == "anonymous":
        raise HTTPException(
            status_code=403, detail="Authentication required for scheduled jobs."
        )
    return effective_user_id(auth, header_user_id=x_aion_user_id)


async def _require_owned_session(session_id: Optional[str], uid: str) -> None:
    """Un job non puo' scrivere nella conversazione di un altro utente."""
    sid = (session_id or "").strip()
    if not sid:
        return
    try:
        sid = normalize_session_id(sid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await assert_conversation_access(
        sid, uid, allow_missing=True, claim_if_missing=True
    )


def _out(d: dict) -> ScheduledJobOut:
    return ScheduledJobOut(**d)


async def _get_owned(job_id: str, user_id: str) -> dict:
    job = await cron_db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Not allowed for this job")
    return job


@router.get("", response_model=ScheduledJobListResponse)
async def list_my_cron_jobs(
    enabled: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=200),
    uid: str = Depends(_cron_user_id),
):
    _require_cron()
    jobs = await cron_db.list_jobs(user_id=uid, enabled=enabled, limit=limit)
    return ScheduledJobListResponse(jobs=[_out(j) for j in jobs], total=len(jobs))


@router.get("/{job_id}", response_model=ScheduledJobOut)
async def get_my_cron_job(job_id: str, uid: str = Depends(_cron_user_id)):
    _require_cron()
    job = await _get_owned(job_id, uid)
    return _out(job)


@router.post("", response_model=ScheduledJobOut)
async def create_my_cron_job(
    body: ScheduledJobCreate,
    uid: str = Depends(_cron_user_id),
):
    _require_cron()
    n = await cron_db.count_jobs_for_user(uid)
    if n >= _max_jobs_per_user():
        raise HTTPException(
            status_code=400,
            detail=f"Max scheduled jobs per user ({_max_jobs_per_user()}) reached.",
        )
    await _require_owned_session(body.session_id, uid)
    try:
        job = await cron_db.create_job(
            user_id=uid,
            name=body.name,
            cron_expression=body.cron_expression,
            prompt=body.prompt,
            profile_slug=body.profile_slug,
            session_mode=body.session_mode,
            session_id=body.session_id,
            sql_query_project=body.sql_query_project,
            timezone=body.timezone,
            description=body.description,
            enabled=body.enabled,
            agent_mode=body.agent_mode,
            created_by="user",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if job.get("enabled"):
        await register_job(job["job_id"])
    return _out(job)


@router.patch("/{job_id}", response_model=ScheduledJobOut)
async def patch_my_cron_job(
    job_id: str,
    body: ScheduledJobUpdate,
    uid: str = Depends(_cron_user_id),
):
    _require_cron()
    await _get_owned(job_id, uid)
    patch = body.model_dump(exclude_unset=True)
    if "session_id" in patch:
        await _require_owned_session(patch.get("session_id"), uid)
    if not patch:
        job = await cron_db.get_job(job_id)
        return _out(job)  # type: ignore[arg-type]
    try:
        updated = await cron_db.update_job(job_id, patch=patch)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not updated:
        raise HTTPException(status_code=404, detail="Job not found")
    await reschedule_job(job_id)
    return _out(updated)


@router.delete("/{job_id}")
async def delete_my_cron_job(job_id: str, uid: str = Depends(_cron_user_id)):
    _require_cron()
    await _get_owned(job_id, uid)
    await unregister_job(job_id)
    ok = await cron_db.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "job_id": job_id}


@router.post("/{job_id}/run-now")
async def run_my_cron_job_now(
    job_id: str,
    background_tasks: BackgroundTasks,
    uid: str = Depends(_cron_user_id),
):
    _require_cron()
    await _get_owned(job_id, uid)
    background_tasks.add_task(execute_job, job_id, trigger="user")
    return {"ok": True, "job_id": job_id, "status": "running"}


@router.get("/{job_id}/runs", response_model=ScheduledRunListResponse)
async def list_my_cron_job_runs(
    job_id: str,
    limit: int = Query(50, ge=1, le=200),
    uid: str = Depends(_cron_user_id),
):
    _require_cron()
    await _get_owned(job_id, uid)
    runs = await cron_db.list_runs(job_id, limit=limit)
    return ScheduledRunListResponse(runs=[ScheduledRunOut(**r) for r in runs])

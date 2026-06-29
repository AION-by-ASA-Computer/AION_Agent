"""APScheduler integration for per-user cron jobs."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.runtime import cron_db
from src.runtime.cron_runner import execute_job

logger = logging.getLogger("aion.cron_scheduler")

_scheduler: Optional[AsyncIOScheduler] = None
_APS_JOB_PREFIX = "aion_cron:"


def cron_enabled() -> bool:
    return os.environ.get("AION_CRON_ENABLED", "0").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _aps_job_id(job_id: str) -> str:
    return f"{_APS_JOB_PREFIX}{job_id}"


async def _fire_job(job_id: str) -> None:
    try:
        await execute_job(job_id, trigger="scheduler")
    except Exception:
        logger.exception("scheduled job fire failed job_id=%s", job_id)


def _parse_cron_fields(expr: str) -> Dict[str, str]:
    parts = (expr or "").strip().split()
    if len(parts) != 5:
        raise ValueError(f"Expected 5-field cron, got {len(parts)} fields")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def register_job_on_scheduler(sched: AsyncIOScheduler, job: Dict[str, Any]) -> None:
    job_id = job["job_id"]
    aps_id = _aps_job_id(job_id)
    if sched.get_job(aps_id):
        sched.remove_job(aps_id)
    if not job.get("enabled"):
        return
    fields = _parse_cron_fields(job["cron_expression"])
    tz = (job.get("timezone") or "UTC").strip() or "UTC"
    trigger = CronTrigger(
        timezone=tz,
        minute=fields["minute"],
        hour=fields["hour"],
        day=fields["day"],
        month=fields["month"],
        day_of_week=fields["day_of_week"],
    )
    sched.add_job(
        _fire_job,
        trigger=trigger,
        id=aps_id,
        args=[job_id],
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=int(os.getenv("AION_CRON_MISFIRE_GRACE_SEC", "300")),
    )
    logger.info(
        "cron registered job_id=%s expr=%s tz=%s",
        job_id[:8],
        job["cron_expression"],
        tz,
    )


def unregister_job_on_scheduler(sched: AsyncIOScheduler, job_id: str) -> None:
    aps_id = _aps_job_id(job_id)
    if sched.get_job(aps_id):
        sched.remove_job(aps_id)


async def reload_all_jobs() -> None:
    sched = get_scheduler()
    if not sched:
        return
    for j in list(sched.get_jobs()):
        if j.id and j.id.startswith(_APS_JOB_PREFIX):
            sched.remove_job(j.id)
    jobs = await cron_db.list_enabled_jobs()
    for job in jobs:
        try:
            register_job_on_scheduler(sched, job)
        except Exception as e:
            logger.warning("cron skip job_id=%s: %s", job.get("job_id"), e)


async def register_job(job_id: str) -> None:
    job = await cron_db.get_job(job_id)
    if not job:
        return
    sched = get_scheduler()
    if sched:
        register_job_on_scheduler(sched, job)


async def reschedule_job(job_id: str) -> None:
    await register_job(job_id)


async def unregister_job(job_id: str) -> None:
    sched = get_scheduler()
    if sched:
        unregister_job_on_scheduler(sched, job_id)


def get_scheduler() -> Optional[AsyncIOScheduler]:
    return _scheduler


def start_scheduler() -> Optional[AsyncIOScheduler]:
    global _scheduler
    if not cron_enabled():
        logger.info("Cron scheduler disabled (AION_CRON_ENABLED=0)")
        return None
    if _scheduler is not None:
        return _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.start()
    logger.info("Cron AsyncIOScheduler started")
    return _scheduler


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Cron scheduler stopped")

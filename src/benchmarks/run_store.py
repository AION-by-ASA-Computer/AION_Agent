from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from src.data.engine import get_async_session_maker
from src.data.models import EvalResult, EvalRun


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_meta(run: EvalRun) -> Dict[str, Any]:
    raw = getattr(run, "metadata_json", None) or "{}"
    try:
        return json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except json.JSONDecodeError:
        return {}


def _merge_meta(run: EvalRun, patch: Dict[str, Any]) -> None:
    meta = _parse_meta(run)
    meta.update(patch)
    run.metadata_json = json.dumps(meta)


async def create_run(
    run_id: str,
    *,
    benchmark_id: str,
    dataset_name: str,
    profile_name: str,
    config: Optional[Dict[str, Any]] = None,
    status: str = "pending",
) -> None:
    async with get_async_session_maker()() as session:
        run = EvalRun(
            id=run_id,
            dataset_name=dataset_name,
            profile_name=profile_name,
            benchmark_id=benchmark_id,
            status=status,
            config_json=json.dumps(config or {}),
            metrics_json="{}",
        )
        _merge_meta(
            run,
            {
                "benchmark_id": benchmark_id,
                "status": status,
                "config": config or {},
            },
        )
        session.add(run)
        await session.commit()


async def ensure_run(
    run_id: str,
    *,
    benchmark_id: str,
    dataset_name: str,
    profile_name: str,
    config: Optional[Dict[str, Any]] = None,
    status: str = "pending",
) -> None:
    """Create eval_runs row if missing (CLI may have created it already)."""
    async with get_async_session_maker()() as session:
        existing = await session.get(EvalRun, run_id)
        if existing is not None:
            return
    await create_run(
        run_id,
        benchmark_id=benchmark_id,
        dataset_name=dataset_name,
        profile_name=profile_name,
        config=config,
        status=status,
    )


async def update_run_progress(
    run_id: str,
    *,
    phase: str,
    progress: Optional[Dict[str, Any]] = None,
) -> None:
    """Update partial metrics while a run is in progress (ingest / query phases)."""
    async with get_async_session_maker()() as session:
        run = await session.get(EvalRun, run_id)
        if not run:
            return
        metrics: Dict[str, Any] = {}
        try:
            metrics = json.loads(run.metrics_json or "{}")
        except json.JSONDecodeError:
            pass
        metrics["phase"] = phase
        metrics["progress"] = progress or {}
        run.metrics_json = json.dumps(metrics)
        _merge_meta(run, {"phase": phase, "progress": progress or {}})
        await session.commit()


async def update_run_status(
    run_id: str,
    *,
    status: str,
    overall_score: Optional[float] = None,
    metrics: Optional[Dict[str, Any]] = None,
    log_path: Optional[str] = None,
    pid: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    async with get_async_session_maker()() as session:
        run = await session.get(EvalRun, run_id)
        if not run:
            return
        run.status = status
        run.benchmark_id = run.benchmark_id or _parse_meta(run).get("benchmark_id")
        if status == "running" and not run.started_at:
            run.started_at = _now()
        if status in ("completed", "failed", "cancelled"):
            run.finished_at = _now()
        if overall_score is not None:
            run.overall_score = overall_score
        if metrics is not None:
            run.metrics_json = json.dumps(metrics)
        if log_path is not None:
            run.log_path = log_path
        if pid is not None:
            run.pid = pid
        patch: Dict[str, Any] = {"status": status}
        if error:
            patch["error"] = error
        if metrics is not None:
            patch["metrics"] = metrics
        _merge_meta(run, patch)
        await session.commit()


async def save_case_result(
    run_id: str,
    *,
    case_id: str,
    input_text: str,
    expected_output: str = "",
    actual_output: str = "",
    score: float,
    reasoning: str = "",
    latency_sec: Optional[float] = None,
) -> None:
    async with get_async_session_maker()() as session:
        er = EvalResult(
            run_id=run_id,
            case_id=case_id,
            input_text=input_text,
            expected_output=expected_output,
            actual_output=actual_output,
            score=score,
            reasoning=reasoning,
            latency_sec=latency_sec,
        )
        session.add(er)
        await session.commit()


async def list_runs(
    *,
    limit: int = 20,
    benchmark_id: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    async with get_async_session_maker()() as session:
        q = select(EvalRun).order_by(EvalRun.created_at.desc()).limit(limit)
        rows = (await session.execute(q)).scalars().all()
        out = []
        for r in rows:
            meta = _parse_meta(r)
            bid = r.benchmark_id or meta.get("benchmark_id")
            st = r.status or meta.get("status")
            if benchmark_id and bid != benchmark_id:
                continue
            if status and st != status:
                continue
            metrics = {}
            try:
                metrics = json.loads(r.metrics_json or "{}")
            except json.JSONDecodeError:
                pass
            out.append(
                {
                    "id": r.id,
                    "benchmark_id": bid,
                    "dataset_name": r.dataset_name,
                    "profile_name": r.profile_name,
                    "overall_score": r.overall_score,
                    "status": st,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "log_path": r.log_path,
                    "metrics_json": metrics,
                }
            )
        return out


async def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    rows = await list_runs(limit=500)
    for r in rows:
        if r["id"] == run_id:
            return r
    return None


async def list_case_results(run_id: str) -> List[Dict[str, Any]]:
    async with get_async_session_maker()() as session:
        q = select(EvalResult).where(EvalResult.run_id == run_id)
        rows = (await session.execute(q)).scalars().all()
        return [
            {
                "case_id": r.case_id,
                "input_text": r.input_text,
                "expected_output": r.expected_output,
                "actual_output": r.actual_output,
                "score": r.score,
                "reasoning": r.reasoning,
                "latency_sec": r.latency_sec,
            }
            for r in rows
        ]

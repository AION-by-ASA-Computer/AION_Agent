from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.memory.mnemos import store as mnemos_store
from src.memory.mnemos.compress import compress_scope

from ..run_store import update_run_progress
from .denoise import boilerplate_note
from .prepare import (
    clear_run_boilerplate,
    collect_trajectory_boilerplate,
    set_run_boilerplate,
    trajectory_text_chunks,
    load_haystack_small,
    load_trajectories_by_ids,
    collect_haystack_trajectory_ids,
)

if TYPE_CHECKING:
    from ..run_log import RunLogger

BENCHMARK_TENANT = "benchmark"


def eval_scope(*, run_id: str, project_slug: str = "lme_v2_small"):
    from src.memory.mnemos.scope import project_scope

    user_id = f"lme_v2_{run_id}"
    return project_scope(BENCHMARK_TENANT, project_slug), user_id


def _bulk_batch_size() -> int:
    return int(os.getenv("AION_LME_V2_INGEST_BATCH_SIZE", "500"))


async def ingest_haystack(
    run_id: str,
    *,
    max_trajectories: Optional[int] = None,
    question_ids: Optional[List[str]] = None,
    project_slug: Optional[str] = None,
    root=None,
    log: Optional["RunLogger"] = None,
) -> Dict[str, Any]:
    """Ingest haystack trajectories as Mnemos project notes."""
    scope, _user_id = eval_scope(
        run_id=run_id, project_slug=project_slug or "lme_v2_small"
    )
    haystack = load_haystack_small(root)

    def _log(msg: str, **fields: Any) -> None:
        if log:
            log.line("ingest", msg, **fields)
        else:
            print(f"[ingest] {msg}", flush=True)

    traj_ids: List[str] = []
    if question_ids:
        seen: set[str] = set()
        for qid in question_ids:
            for tid in collect_haystack_trajectory_ids(haystack, question_id=qid):
                if tid not in seen:
                    seen.add(tid)
                    traj_ids.append(tid)
    else:
        traj_ids = collect_haystack_trajectory_ids(haystack)

    if max_trajectories is None and question_ids:
        pass
    else:
        if max_trajectories is None:
            max_trajectories = int(os.getenv("AION_LME_V2_MAX_TRAJECTORIES", "100"))
        traj_ids = traj_ids[: int(max_trajectories)]

    _log(
        f"loading {len(traj_ids)} trajectories (streaming trajectories.jsonl)…",
        trajectory_ids_sample=traj_ids[:10],
        question_ids=question_ids,
    )
    all_trajs = load_trajectories_by_ids(traj_ids, root)
    _log(
        f"loaded {len(all_trajs)}/{len(traj_ids)} trajectories; detecting boilerplate…",
        missing_ids=[t for t in traj_ids if str(t) not in all_trajs][:20],
    )

    boiler = collect_trajectory_boilerplate(all_trajs)
    set_run_boilerplate(boiler)
    _log(f"boilerplate lines: {len(boiler)}")

    notes_written = 0
    trajectories_found = 0
    per_traj_notes: List[Dict[str, Any]] = []
    pending: List[str] = []

    if boiler:
        chrome = boilerplate_note(boiler)
        pending.append(chrome)

    async def _flush_pending(force_tid: str = "batch") -> None:
        nonlocal notes_written, pending
        if not pending:
            return
        batch_size = _bulk_batch_size()
        while pending:
            batch = pending[:batch_size]
            del pending[:batch_size]
            written = await mnemos_store.insert_notes_bulk(
                scope,
                batch,
                category="fact",
                importance=3,
                source_session_id=f"lme_ingest_{force_tid}",
            )
            notes_written += written

    for idx, tid in enumerate(traj_ids, start=1):
        traj = all_trajs.get(str(tid))
        if not traj:
            continue
        trajectories_found += 1
        traj_notes = 0
        for chunk in trajectory_text_chunks(traj):
            pending.append(chunk)
            traj_notes += 1
            if len(pending) >= _bulk_batch_size():
                await _flush_pending(str(tid))
        per_traj_notes.append({"trajectory_id": tid, "notes": traj_notes})

        if idx == 1 or idx % 5 == 0 or idx == len(traj_ids):
            await _flush_pending(str(tid))
            _log(
                f"trajectory {idx}/{len(traj_ids)} ({notes_written} notes written so far)",
                last_trajectory_id=tid,
                last_trajectory_notes=traj_notes,
            )
            await update_run_progress(
                run_id,
                phase="ingest",
                progress={
                    "trajectories_done": idx,
                    "trajectories_total": len(traj_ids),
                    "notes_written": notes_written,
                },
            )

    await _flush_pending("final")
    clear_run_boilerplate()

    compressed = 0
    if os.getenv("AION_LME_V2_COMPRESS_SCOPE", "0") == "1":
        _log("compressing scope digests…")
        compressed = await compress_scope(scope)

    stats = {
        "notes_written": notes_written,
        "trajectories_requested": len(traj_ids),
        "trajectories_ingested": trajectories_found,
        "digests_compressed": compressed,
        "boilerplate_lines": len(boiler),
        "scope": f"{scope.scope_type}:{scope.scope_key}",
        "trajectory_ids": traj_ids,
        "per_trajectory_notes": per_traj_notes,
    }
    _log(
        f"ingest complete: {json.dumps({k: v for k, v in stats.items() if k != 'per_trajectory_notes'})}"
    )
    if log:
        log.debug_record({"phase": "ingest", "ingest": stats})
    return stats

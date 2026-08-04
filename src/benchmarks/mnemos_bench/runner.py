from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.data.engine import get_async_session_maker
from src.data.models import LtmNote
from src.memory.mnemos import store as mnemos_store
from src.memory.mnemos.recall import recall, recall_across_scopes
from src.memory.mnemos.scope import project_scope, user_scope
from src.memory.mnemos.types import MemoryScope
from src.memory.mnemos.wake import wake, wake_budget

from ..paths import run_artifact_dir
from ..run_log import RunLogger
from ..run_store import ensure_run, save_case_result, update_run_progress, update_run_status

BENCH_TENANT = "mnemos_bench"


def _scope(scope_type: str, scope_key: str) -> MemoryScope:
    if scope_type == "project":
        return project_scope(BENCH_TENANT, scope_key)
    return user_scope(BENCH_TENANT, scope_key)


def _normalize_setup_notes(raw: Any) -> List[Dict[str, Any]]:
    """Accept plain strings (legacy) or dicts with per-note attributes."""
    out: List[Dict[str, Any]] = []
    for item in raw or []:
        if isinstance(item, str):
            out.append({"content": item, "category": "fact", "importance": 3})
            continue
        out.append(
            {
                "content": str(item.get("content") or ""),
                "category": str(item.get("category") or "fact"),
                "importance": int(item.get("importance") or 3),
                "age_days": item.get("age_days"),
                "supersedes": item.get("supersedes"),
                "valid_from": item.get("valid_from"),
                "valid_to": item.get("valid_to"),
            }
        )
    return out


async def _backdate_note(note_id: int, age_days: float) -> None:
    """Rewrite created_at so recency-sensitive ranking can be exercised."""
    async with get_async_session_maker()() as session:
        await session.execute(
            text("UPDATE ltm_notes SET created_at = datetime('now', :delta) WHERE id = :id"),
            {"delta": f"-{float(age_days)} days", "id": int(note_id)},
        )
        await session.commit()


async def _parse_dt(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


async def _insert_setup_notes(
    scope: MemoryScope,
    specs: List[Dict[str, Any]],
    *,
    run_id: str,
) -> List[Any]:
    inserted: List[Any] = []
    for spec in specs:
        content = spec.get("content") or ""
        if len(content.strip()) < 3:
            continue
        vf = await _parse_dt(spec.get("valid_from"))
        vt = await _parse_dt(spec.get("valid_to"))
        note = await mnemos_store.insert_note(
            scope,
            content=content,
            category=str(spec.get("category") or "fact"),
            importance=int(spec.get("importance") or 3),
            source_session_id=run_id,
            valid_from=vf,
        )
        inserted.append(note)
        if vt is not None:
            async with get_async_session_maker()() as session:
                row = await session.get(LtmNote, note.id)
                if row:
                    if vf is not None:
                        row.valid_from = vf
                    row.valid_to = vt
                    await session.commit()
        age = spec.get("age_days")
        if age:
            await _backdate_note(note.id, float(age))
        sup = spec.get("supersedes")
        if sup is not None and 0 <= int(sup) < len(inserted) - 1:
            await mnemos_store.supersede_note(inserted[int(sup)].id, note)
    return inserted


async def _insert_filler(
    scope: MemoryScope,
    filler: Dict[str, Any],
    *,
    run_id: str,
) -> int:
    count = int(filler.get("count") or 0)
    if count <= 0:
        return 0
    template = str(filler.get("template") or "Routine log entry {i} no action required")
    bodies = [template.format(i=i) for i in range(1, count + 1)]
    return await mnemos_store.insert_notes_bulk(
        scope, bodies, category="event", importance=1, source_session_id=run_id
    )


def _score_recall(
    rows: List[Dict[str, Any]],
    *,
    expected_substrings: List[str],
    forbidden_substrings: List[str],
    min_hits: int,
    top_k: Optional[int] = None,
) -> Dict[str, Any]:
    """Expected substrings are checked inside the top_k window; forbidden across all rows."""
    window = rows if top_k is None else rows[: max(1, int(top_k))]
    joined = "\n".join(str(r.get("content") or "") for r in window).lower()
    joined_all = "\n".join(str(r.get("content") or "") for r in rows).lower()
    hits = [s for s in expected_substrings if s.lower() in joined]
    forbidden = [s for s in forbidden_substrings if s.lower() in joined_all]
    ok = len(hits) >= min_hits and not forbidden
    if ok and min_hits == 0 and not expected_substrings:
        ok = not forbidden
    if ok:
        reason = "ok"
    elif forbidden:
        reason = "forbidden_hit"
    elif top_k is not None and any(
        s.lower() in joined_all for s in expected_substrings if s.lower() not in joined
    ):
        reason = "rank_miss"
    else:
        reason = "miss"
    return {
        "score": 1.0 if ok else 0.0,
        "hits": hits,
        "forbidden": forbidden,
        "returned": len(rows),
        "reason": reason,
    }


def _render_report(run_id: str, metrics: Dict[str, Any], dataset_path: str) -> str:
    lines = [
        f"# Mnemos Bench — {run_id}",
        "",
        f"- **Dataset:** `{dataset_path}`",
        f"- **Cases:** {metrics.get('case_count', 0)}",
        f"- **Passed:** {metrics.get('passed', 0)}",
        f"- **Failed:** {metrics.get('failed', 0)}",
        f"- **Accuracy:** {metrics.get('accuracy_overall', 0) * 100:.1f}%",
        f"- **Embedding recall:** `{metrics.get('embedding_recall', '0')}`",
        f"- **Total time:** {metrics.get('latency_total_sec', 0):.2f}s",
        "",
    ]
    by_cat = metrics.get("accuracy_by_category") or {}
    if by_cat:
        lines.extend(["## Accuracy by category", "", "| Category | Passed | Total | Accuracy |", "|----------|--------|-------|----------|"])
        for cat, row in sorted(by_cat.items()):
            lines.append(
                f"| {cat} | {row.get('passed', 0)} | {row.get('total', 0)} | "
                f"{row.get('accuracy', 0) * 100:.1f}% |"
            )
        lines.append("")
    lines.extend([
        "## Per case",
        "",
        "| Case | Category | Score | Reason | Latency | Query |",
        "|------|----------|-------|--------|---------|-------|",
    ])
    for row in metrics.get("cases") or []:
        q = str(row.get("query") or "").replace("|", "\\|")[:50]
        lines.append(
            f"| {row.get('case_id')} | {row.get('category', '')} | {row.get('score')} "
            f"| {row.get('reason')} | {float(row.get('latency_sec', 0)):.2f}s | {q} |"
        )
    lines.append("")
    return "\n".join(lines)


def _accuracy_by_category(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        cat = str(row.get("category") or "uncategorized")
        bucket = buckets.setdefault(cat, {"passed": 0, "total": 0, "accuracy": 0.0})
        bucket["total"] += 1
        if row.get("score") == 1.0:
            bucket["passed"] += 1
    for bucket in buckets.values():
        total = bucket["total"] or 1
        bucket["accuracy"] = bucket["passed"] / total
    return buckets


def _print_banner(
    log: RunLogger,
    *,
    run_id: str,
    dataset_path: str,
    case_count: int,
    hybrid_env: str,
) -> None:
    mode = "hybrid FTS+embedding" if hybrid_env == "1" else "FTS-only"
    log.line("banner", "═" * 56)
    log.line("banner", "  Mnemos Bench — recall@k validation (dev CLI)")
    log.line("banner", f"  run_id:    {run_id}")
    log.line("banner", f"  dataset:   {dataset_path}")
    log.line("banner", f"  recall:    {mode}")
    log.line("banner", f"  cases:     {case_count}")
    log.line("banner", "═" * 56)


async def run_mnemos_bench(
    *,
    run_id: str,
    dataset_path: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    log = RunLogger(run_id)
    cfg = config or {}
    path = Path(dataset_path)
    if not path.is_file():
        log.line("error", f"dataset not found: {path}")
        await update_run_status(run_id, status="failed", error=f"dataset not found: {path}")
        return {"error": f"dataset not found: {path}"}

    payload = json.loads(path.read_text(encoding="utf-8"))
    title = str(payload.get("title") or "Mnemos recall micro-benchmark")
    cases: List[Dict[str, Any]] = payload.get("cases") or []
    max_cases = cfg.get("max_cases")
    if max_cases is not None:
        cases = cases[: int(max_cases)]

    hybrid_env = os.getenv("AION_MNEMOS_EMBEDDING_RECALL", "0")
    await ensure_run(
        run_id,
        benchmark_id="mnemos_bench",
        dataset_name=str(path),
        profile_name="n/a",
        config=cfg,
        status="running",
    )
    await update_run_status(run_id, status="running")

    _print_banner(
        log,
        run_id=run_id,
        dataset_path=str(path),
        case_count=len(cases),
        hybrid_env=hybrid_env,
    )
    if title:
        log.line("init", title)

    from src.memory.mnemos.store import ensure_ltm_schema

    await ensure_ltm_schema()

    per_case_path = run_artifact_dir(run_id) / "per_case.jsonl"
    if per_case_path.is_file():
        per_case_path.unlink()
    rows: List[Dict[str, Any]] = []
    t0 = time.perf_counter()

    for idx, case in enumerate(cases, start=1):
        case_id = str(case.get("id") or f"case_{idx}")
        scope_key = f"{run_id}_{case_id}_{uuid.uuid4().hex[:6]}"
        scope = _scope(str(case.get("scope_type") or "user"), scope_key)

        setup_specs = _normalize_setup_notes(case.get("setup_notes"))
        filler = case.get("filler") or {}
        filler_before = str(filler.get("position") or "before") == "before"

        log.line(
            "case",
            f"[{idx}/{len(cases)}] {case_id} — inserting {len(setup_specs)} notes"
            + (f" + {filler.get('count')} filler" if filler else "")
            + "…",
        )

        if filler and filler_before:
            await _insert_filler(scope, filler, run_id=run_id)

        inserted_notes = await _insert_setup_notes(scope, setup_specs, run_id=run_id)
        if filler and not filler_before:
            await _insert_filler(scope, filler, run_id=run_id)
        hard_idx = case.get("hard_delete_index")
        if hard_idx is not None and 0 <= int(hard_idx) < len(inserted_notes):
            await mnemos_store.forget_note(inserted_notes[int(hard_idx)].id, hard=True)
            await mnemos_store.upsert_digest(
                scope,
                0,
                max(2, len(inserted_notes)),
                inserted_notes[int(hard_idx)].content,
                ready=True,
            )

        extra_scope: Optional[MemoryScope] = None
        extra_scope_type = case.get("extra_scope_type")
        if extra_scope_type:
            extra_scope = _scope(str(extra_scope_type), scope_key)
            await _insert_setup_notes(
                extra_scope,
                _normalize_setup_notes(case.get("extra_scope_notes")),
                run_id=run_id,
            )

        query = str(case.get("query") or "")
        recall_limit = int(case.get("recall_limit") or 5)
        as_of = await _parse_dt(case.get("as_of"))
        prefer_hybrid = bool(case.get("prefer_hybrid"))
        prev_hybrid = os.environ.get("AION_MNEMOS_EMBEDDING_RECALL")
        if prefer_hybrid:
            os.environ["AION_MNEMOS_EMBEDDING_RECALL"] = "1"

        t_case = time.perf_counter()
        recalled: List[Dict[str, Any]] = []
        score_dbg: Dict[str, Any] = {"score": 0.0, "reason": "error", "hits": [], "returned": 0}
        try:
            if str(case.get("recall_scope") or "") == "across" and extra_scope is not None:
                recalled = await recall_across_scopes(
                    [scope, extra_scope], query, limit=recall_limit, as_of=as_of
                )
            else:
                recalled = await recall(scope, query, limit=recall_limit, as_of=as_of)
            min_hits_raw = case.get("min_hits")
            min_hits = int(min_hits_raw) if min_hits_raw is not None else 1
            score_dbg = _score_recall(
                recalled,
                expected_substrings=list(case.get("expected_substrings") or []),
                forbidden_substrings=list(case.get("forbidden_substrings") or []),
                min_hits=min_hits,
                top_k=case.get("expect_top_k"),
            )
            wake_forbidden = list(case.get("wake_forbidden_substrings") or [])
            if wake_forbidden:
                wake_rows = await wake(scope, wake_budget())
                wake_text = "\n".join(
                    f"{r.get('line') or ''} {r.get('summary') or ''} {r.get('content') or ''}"
                    for r in wake_rows
                ).lower()
                if any(s.lower() in wake_text for s in wake_forbidden):
                    score_dbg["score"] = 0.0
                    score_dbg["reason"] = "wake_leak"

            neg_scope_type = case.get("negative_scope_type")
            if neg_scope_type:
                neg_key = f"{scope_key}_neg"
                neg_scope = _scope(str(neg_scope_type), neg_key)
                for note in case.get("negative_notes") or []:
                    await mnemos_store.insert_note(
                        neg_scope,
                        content=str(note),
                        category="fact",
                        importance=1,
                        source_session_id=run_id,
                    )
                neg_rows = await recall(
                    neg_scope,
                    str(case.get("negative_query") or query),
                    limit=recall_limit,
                )
                neg_joined = "\n".join(r.get("content", "") for r in neg_rows).lower()
                for sub in case.get("expected_substrings") or []:
                    if sub.lower() in neg_joined:
                        score_dbg["score"] = 0.0
                        score_dbg["reason"] = "scope_leak"
                        break
        finally:
            if prefer_hybrid:
                if prev_hybrid is None:
                    os.environ.pop("AION_MNEMOS_EMBEDDING_RECALL", None)
                else:
                    os.environ["AION_MNEMOS_EMBEDDING_RECALL"] = prev_hybrid

        latency = time.perf_counter() - t_case
        mark = "PASS" if score_dbg["score"] == 1.0 else "FAIL"
        top_snip = (recalled[0].get("content") or "")[:100] if recalled else "(no results)"
        row = {
            "case_id": case_id,
            "category": str(case.get("category") or "uncategorized"),
            "query": query,
            "score": score_dbg["score"],
            "latency_sec": latency,
            "reason": score_dbg["reason"],
            "hits": score_dbg["hits"],
            "returned": score_dbg["returned"],
            "scope": f"{scope.scope_type}:{scope.scope_key}",
            "embedding_recall": "1" if prefer_hybrid else hybrid_env,
            "top_result": top_snip,
        }
        rows.append(row)
        with open(per_case_path, "a", encoding="utf-8") as pf:
            pf.write(json.dumps(row) + "\n")

        await save_case_result(
            run_id,
            case_id=case_id,
            input_text=query,
            expected_output=",".join(case.get("expected_substrings") or []),
            actual_output=" | ".join(r.get("content", "") for r in recalled[:3]),
            score=score_dbg["score"],
            reasoning=f"reason={score_dbg['reason']}; hits={score_dbg['hits']}",
            latency_sec=latency,
        )

        log.line(
            "result",
            f"  {mark}  {case_id}  score={score_dbg['score']}  "
            f"reason={score_dbg['reason']}  {latency:.2f}s  "
            f"hits={score_dbg['hits']}",
        )
        log.line("result", f"         query: {query[:120]}")
        log.line("result", f"         top:   {top_snip}")

        await update_run_progress(
            run_id,
            phase="query",
            progress={"cases_done": idx, "cases_total": len(cases)},
        )

    passed = sum(1 for r in rows if r.get("score") == 1.0)
    by_category = _accuracy_by_category(rows)
    metrics = {
        "benchmark_id": "mnemos_bench",
        "title": title,
        "dataset": str(path),
        "run_id": run_id,
        "case_count": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "accuracy_overall": passed / len(rows) if rows else 0.0,
        "accuracy_by_category": by_category,
        "latency_total_sec": time.perf_counter() - t0,
        "embedding_recall": hybrid_env,
        "cases": rows,
    }
    artifact_dir = run_artifact_dir(run_id)
    metrics_path = artifact_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    report_path = artifact_dir / "REPORT.md"
    report_path.write_text(_render_report(run_id, metrics, str(path)), encoding="utf-8")

    log.line("banner", "═" * 56)
    log.line(
        "done",
        f"  {passed}/{len(rows)} passed  "
        f"({metrics['accuracy_overall'] * 100:.1f}%)  "
        f"total {metrics['latency_total_sec']:.1f}s",
    )
    if by_category:
        log.line("done", "  by category:")
        for cat, row in sorted(by_category.items()):
            log.line(
                "done",
                f"    {cat}: {row['passed']}/{row['total']} "
                f"({row['accuracy'] * 100:.0f}%)",
            )
    log.line("done", f"  artifacts → {artifact_dir}/")
    log.line("done", f"    metrics.json   per_case.jsonl   run.log   REPORT.md")
    log.line("banner", "═" * 56)

    await update_run_status(
        run_id,
        status="completed",
        overall_score=metrics["accuracy_overall"],
        metrics=metrics,
    )
    return metrics

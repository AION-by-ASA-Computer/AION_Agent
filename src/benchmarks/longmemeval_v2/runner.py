from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from ..env_config import (
    apply_benchmark_isolation_env,
    apply_mnemos_env,
    resolve_project_slug,
)
from ..paths import run_artifact_dir
from ..registry import mnemos_config_snapshot, write_run_config
from ..run_log import RunLogger
from ..run_store import save_case_result, update_run_progress, update_run_status
from .agent_query import answer_question_with_agent
from .ingest import ingest_haystack
from .metrics import aggregate_metrics, render_report_md
from .prepare import dataset_root, is_dataset_ready, load_questions, normalize_ability
from .query import explain_score
from .scoring import (
    eval_function_family,
    question_eval_function,
    requires_image,
    score_case,
)


def _skip_image_questions() -> bool:
    return os.getenv("AION_LME_V2_SKIP_IMAGE_QUESTIONS", "1") == "1"


def _default_profile(profile_name: str) -> str:
    if profile_name and profile_name != "generic_assistant":
        return profile_name
    return os.getenv("AION_LME_V2_AGENT_PROFILE", "benchmark_memory")


async def run_longmemeval_v2_small(
    *,
    run_id: str,
    profile_name: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    log = RunLogger(run_id)

    if not is_dataset_ready():
        await update_run_status(run_id, status="failed", error="dataset not prepared")
        return {"error": "dataset not prepared"}

    cfg = config or {}
    apply_mnemos_env(cfg)
    apply_benchmark_isolation_env(config=cfg)
    max_questions = cfg.get("max_questions")
    max_trajectories = cfg.get("max_trajectories")
    project_slug = resolve_project_slug(run_id, cfg)
    agent_profile = _default_profile(profile_name)

    llm_snapshot: Dict[str, Any] = {}
    try:
        from src.runtime.llm_adapter import resolve_llm_credentials

        api_base, model, _ = resolve_llm_credentials()
        llm_snapshot = {
            "api_base_url": api_base,
            "model": model,
            "source": "llm_providers (default)",
        }
    except Exception as exc:
        llm_snapshot = {"error": str(exc)}

    log.line(
        "init",
        "benchmark run starting",
        run_id=run_id,
        profile_name=agent_profile,
        project_slug=project_slug,
        llm=llm_snapshot,
        config=cfg,
    )

    write_run_config(
        run_id,
        {
            "benchmark_id": "longmemeval_v2_small",
            "profile_name": agent_profile,
            "project_slug": project_slug,
            "llm": llm_snapshot,
            "mnemos": mnemos_config_snapshot(cfg),
            "max_questions": max_questions,
            "max_trajectories": max_trajectories,
        },
    )
    await update_run_status(run_id, status="running")

    root = dataset_root()
    questions = load_questions(root)
    if max_questions is not None:
        questions = questions[: int(max_questions)]

    question_ids = [
        str(q.get("question_id") or q.get("id") or f"q_{i}")
        for i, q in enumerate(questions)
    ]
    ingest_stats = await ingest_haystack(
        run_id,
        max_trajectories=max_trajectories,
        question_ids=question_ids if question_ids else None,
        project_slug=project_slug,
        root=root,
        log=log,
    )

    per_case_path = run_artifact_dir(run_id) / "per_case.jsonl"
    rows: list[Dict[str, Any]] = []
    skipped_image = 0

    log.line(
        "query",
        f"starting {len(questions)} questions after ingest",
        notes_written=ingest_stats.get("notes_written", 0),
        scope=ingest_stats.get("scope"),
        agent_profile=agent_profile,
    )
    await update_run_progress(
        run_id,
        phase="query",
        progress={"questions_total": len(questions), "questions_done": 0},
    )

    scored_idx = 0
    for idx, q in enumerate(questions):
        qid = str(q.get("question_id") or q.get("id") or f"q_{idx}")
        qtext = str(q.get("question") or q.get("text") or q.get("input") or "")
        gold = str(
            q.get("answer")
            or q.get("expected_answer")
            or q.get("expected_output")
            or ""
        )
        ability = normalize_ability(
            q.get("ability")
            or q.get("memory_ability")
            or q.get("question_type")
            or q.get("category")
        )
        eval_spec = question_eval_function(q)
        eval_family = eval_function_family(q)
        needs_image = requires_image(q)

        if needs_image and _skip_image_questions():
            skipped_image += 1
            row = {
                "case_id": qid,
                "question": qtext,
                "expected_output": gold,
                "actual_output": "",
                "score": None,
                "latency_sec": 0.0,
                "ability": ability,
                "eval_function": eval_family,
                "requires_image": True,
                "skipped": "skipped_image",
                "evidence": "",
                "error": None,
                "llm_model": llm_snapshot.get("model"),
                "score_reason": "skipped_image",
            }
            rows.append(row)
            with open(per_case_path, "a", encoding="utf-8") as pf:
                pf.write(json.dumps(row) + "\n")
            log.debug_record(
                {"phase": "query", "case_id": qid, "skipped": "skipped_image"}
            )
            continue

        qa_debug: Dict[str, Any] = {}
        score_dbg: Dict[str, Any] = {}
        try:
            pred, latency, qa_debug = await answer_question_with_agent(
                qtext,
                run_id=run_id,
                profile_name=agent_profile,
                project_slug=project_slug,
                session_id=f"{run_id}_{qid}",
                config=cfg,
            )
            score_dbg = await score_case(
                question=qtext,
                expected=gold,
                actual=pred,
                raw_actual=str(qa_debug.get("raw_text") or ""),
                eval_function=eval_spec,
            )
            score_dbg["heuristic"] = explain_score(gold, pred)
            score = float(score_dbg["score"])
            err_msg = "" if pred else "empty_llm_response"
        except Exception as exc:
            pred = ""
            latency = 0.0
            score = 0.0
            score_dbg = {"reason": "exception", "error": str(exc), "score": 0.0}
            err_msg = str(exc)

        row = {
            "case_id": qid,
            "question": qtext,
            "expected_output": gold,
            "actual_output": pred,
            "score": score,
            "latency_sec": latency,
            "ability": ability,
            "eval_function": eval_family,
            "requires_image": needs_image,
            "evidence": "",
            "error": err_msg or None,
            "llm_model": llm_snapshot.get("model"),
            "score_reason": score_dbg.get("reason"),
            "memory_recall_calls": qa_debug.get("memory_recall_calls"),
        }
        rows.append(row)
        with open(per_case_path, "a", encoding="utf-8") as pf:
            pf.write(json.dumps(row) + "\n")

        log.debug_record(
            {
                "phase": "query",
                "case_id": qid,
                "ability": ability,
                "eval_function": eval_family,
                "eval_function_spec": eval_spec,
                "requires_image": needs_image,
                "expected_output": gold,
                "actual_output": pred,
                "score": score,
                "score_debug": score_dbg,
                "latency_sec": latency,
                "error": err_msg or None,
                "qa": qa_debug,
                "llm": llm_snapshot,
            }
        )

        await save_case_result(
            run_id,
            case_id=qid,
            input_text=qtext,
            expected_output=gold,
            actual_output=pred,
            score=score,
            reasoning=(
                f"ability={ability}; score_reason={score_dbg.get('reason')}"
                + (f"; error={err_msg}" if err_msg else "")
                + (
                    f"; memory_recall_calls={qa_debug.get('memory_recall_calls')}"
                    if qa_debug.get("memory_recall_calls") is not None
                    else ""
                )
            ),
            latency_sec=latency,
        )

        scored_idx += 1
        if scored_idx % 5 == 0 or idx + 1 == len(questions):
            log.line("query", f"{idx + 1}/{len(questions)} questions done")
            await update_run_progress(
                run_id,
                phase="query",
                progress={
                    "questions_done": idx + 1,
                    "questions_total": len(questions),
                },
            )

    metrics = aggregate_metrics(rows)
    metrics["ingest"] = ingest_stats
    metrics["errors"] = sum(1 for r in rows if r.get("error"))
    metrics["skipped_image"] = skipped_image
    metrics["score_reasons"] = {
        str(r.get("case_id")): r.get("score_reason") for r in rows
    }
    metrics_path = run_artifact_dir(run_id) / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    report_path = run_artifact_dir(run_id) / "REPORT.md"
    report_path.write_text(render_report_md(run_id, metrics), encoding="utf-8")

    log.line(
        "done",
        f"accuracy={metrics['accuracy_overall'] * 100:.1f}% cases={metrics['case_count']}",
        score_reasons=metrics.get("score_reasons"),
        skipped_image=skipped_image,
        debug_file=str(run_artifact_dir(run_id) / "debug.jsonl"),
    )

    await update_run_status(
        run_id,
        status="completed",
        overall_score=metrics["accuracy_overall"],
        metrics=metrics,
    )
    return metrics

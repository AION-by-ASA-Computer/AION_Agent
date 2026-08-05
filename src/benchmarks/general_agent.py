from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, Optional

from src.agent_pipeline import AgentPipeline
from src.eval.evaluators import evaluate_case
from src.eval.judge import evaluate_with_llm_judge
from src.main import get_agent, set_event_loop

from .registry import mnemos_config_snapshot, write_run_config
from .run_store import save_case_result, update_run_status


async def run_general_agent_benchmark(
    *,
    run_id: str,
    dataset_path: str,
    profile_name: str,
    threshold: float = 0.0,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run JSON agent eval cases through AgentPipeline."""
    write_run_config(
        run_id,
        {
            "benchmark_id": "general_agent",
            "profile_name": profile_name,
            "dataset_path": dataset_path,
            "threshold": threshold,
            "mnemos": mnemos_config_snapshot(config),
        },
    )
    await update_run_status(run_id, status="running")

    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    cases = dataset.get("cases", [])
    if not cases:
        await update_run_status(run_id, status="failed", error="no cases")
        return {"overall_score": 0.0, "error": "no cases"}

    total_score = 0.0
    per_case_path = None
    from .paths import run_artifact_dir

    per_case_path = run_artifact_dir(run_id) / "per_case.jsonl"

    for idx, case in enumerate(cases):
        case_id = case.get("id", f"case_{idx}")
        input_text = case["input_text"]
        eval_type = case.get("eval_type", "exact_match")
        session_id = f"{run_id}_{case_id}"

        agent_instance, p_name = await get_agent(
            profile_name, session_id=session_id, user_id="eval"
        )
        pipeline = AgentPipeline(
            agent_instance, session_id=session_id, profile_name=p_name, user_id="eval"
        )

        start_t = time.monotonic()
        res = await pipeline.run(input_text)
        latency = time.monotonic() - start_t
        actual_output = res.get("text", "")

        reasoning = ""
        if eval_type == "llm_judge":
            score, reasoning = await evaluate_with_llm_judge(case, actual_output)
        else:
            score = evaluate_case(case, actual_output)

        total_score += score
        row = {
            "case_id": case_id,
            "input_text": input_text,
            "expected_output": case.get("expected_output", ""),
            "actual_output": actual_output,
            "score": score,
            "reasoning": reasoning,
            "latency_sec": latency,
        }
        with open(per_case_path, "a", encoding="utf-8") as pf:
            pf.write(json.dumps(row) + "\n")

        await save_case_result(
            run_id,
            case_id=case_id,
            input_text=input_text,
            expected_output=case.get("expected_output", ""),
            actual_output=actual_output,
            score=score,
            reasoning=reasoning,
            latency_sec=latency,
        )

    overall = total_score / len(cases)
    metrics = {
        "accuracy_overall": overall,
        "case_count": len(cases),
        "threshold": threshold,
        "passed": overall >= threshold,
    }
    from .paths import run_artifact_dir

    metrics_path = run_artifact_dir(run_id) / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    await update_run_status(
        run_id,
        status="completed",
        overall_score=overall,
        metrics=metrics,
    )
    return metrics


async def run_evaluation(
    dataset_path: str, profile_name: str, threshold: float = 0.8
) -> float:
    """Backward-compatible entry used by src.eval.cli and Optuna."""
    run_id = f"eval_{uuid.uuid4().hex[:8]}"
    from .run_store import create_run

    await create_run(
        run_id,
        benchmark_id="general_agent",
        dataset_name=dataset_path,
        profile_name=profile_name,
        status="running",
    )
    metrics = await run_general_agent_benchmark(
        run_id=run_id,
        dataset_path=dataset_path,
        profile_name=profile_name,
        threshold=threshold,
    )
    return float(metrics.get("accuracy_overall", 0.0))

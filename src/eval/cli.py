import argparse
import asyncio
import json
import time
import uuid
import sys
from datetime import datetime
from src.main import get_agent, set_event_loop
from src.agent_pipeline import AgentPipeline
from src.eval.evaluators import evaluate_case
from src.eval.judge import evaluate_with_llm_judge
from src.data.engine import get_async_session_maker
from src.data.models import EvalRun, EvalResult


async def run_evaluation(dataset_path: str, profile_name: str, threshold: float):
    # Load dataset
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    cases = dataset.get("cases", [])
    if not cases:
        print("Nessun test case trovato nel dataset.")
        return False

    run_id = f"eval_{uuid.uuid4().hex[:8]}"
    print(
        f"Avvio Evaluation Run: {run_id} | Dataset: {dataset_path} | Profilo: {profile_name}"
    )

    results = []
    total_score = 0.0

    # Init Run in DB
    async with get_async_session_maker()() as session:
        new_run = EvalRun(
            id=run_id, dataset_name=dataset_path, profile_name=profile_name
        )
        session.add(new_run)
        await session.commit()

    # We use a unique session for each test case
    for idx, case in enumerate(cases):
        case_id = case.get("id", f"case_{idx}")
        input_text = case["input_text"]
        eval_type = case.get("eval_type", "exact_match")

        print(f"\n[Case {case_id}] Input: {input_text[:50]}...")

        # Setup pipeline
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

        # Eval
        reasoning = ""
        if eval_type == "llm_judge":
            score, reasoning = await evaluate_with_llm_judge(case, actual_output)
        else:
            score = evaluate_case(case, actual_output)

        print(f"   -> Score: {score:.2f} | Latency: {latency:.2f}s")
        if eval_type == "llm_judge":
            print(f"   -> Judge Reasoning: {reasoning}")

        total_score += score

        # Save Result to DB
        async with get_async_session_maker()() as session:
            er = EvalResult(
                run_id=run_id,
                case_id=case_id,
                input_text=input_text,
                expected_output=case.get("expected_output", ""),
                actual_output=actual_output,
                score=score,
                reasoning=reasoning,
                latency_sec=latency,
            )
            session.add(er)
            await session.commit()

    overall_score = total_score / len(cases)

    async with get_async_session_maker()() as session:
        run = await session.get(EvalRun, run_id)
        if run:
            run.overall_score = overall_score
            await session.commit()

    print(f"\n======================================")
    print(f"EVALUATION COMPLETATA (Run ID: {run_id})")
    print(f"Score Globale: {overall_score:.2f} / 1.00")
    print(f"Soglia (Threshold): {threshold:.2f}")

    if overall_score >= threshold:
        print("✅ GATING PASSATO: L'agente rispetta i criteri.")
    else:
        print("❌ GATING FALLITO: Regressione rilevata.")

    return overall_score


def main():
    parser = argparse.ArgumentParser(description="AION Agent Evaluation Harness")
    parser.add_argument(
        "--dataset", type=str, required=True, help="Path al file JSON del dataset"
    )
    parser.add_argument(
        "--profile", type=str, default="AION Core", help="Profilo agente da valutare"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        help="Soglia minima di successo (0.0 - 1.0) per passare la CI",
    )

    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    set_event_loop(loop)

    success = loop.run_until_complete(
        run_evaluation(args.dataset, args.profile, args.threshold)
    )

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()

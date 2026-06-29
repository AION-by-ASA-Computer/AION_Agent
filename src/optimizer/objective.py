import optuna
import os
import time
import asyncio
from src.eval.cli import run_evaluation


def aion_agent_objective(trial):
    """
    Optuna objective function for optimizing AION Agent hyperparameters.
    Uses the real Eval Harness (Fase 11) to compute scores.
    """
    # 1. Hyperparameters to optimize
    max_tokens = trial.suggest_int("max_tokens", 256, 4096, step=256)
    temperature = trial.suggest_float("temperature", 0.0, 1.0)
    top_p = trial.suggest_float("top_p", 0.1, 1.0)
    stm_max_turns = trial.suggest_int("stm_max_turns", 5, 20)

    # 2. Setup environment overrides for the trial
    os.environ["AION_MAX_TOKENS"] = str(max_tokens)
    os.environ["AION_TEMPERATURE"] = str(temperature)
    os.environ["AION_TOP_P"] = str(top_p)
    os.environ["AION_STM_MAX_TURNS"] = str(stm_max_turns)

    # 3. Execution
    dataset = os.getenv(
        "AION_OPTIMIZER_DATASET", "data/eval_datasets/optimization_base.json"
    )

    if os.path.exists(dataset):
        print(f"Trial {trial.number}: Running real evaluation on {dataset}...")
        try:
            # Run the async evaluation in a way that works inside Optuna (blocking)
            loop = asyncio.get_event_loop()
            score = loop.run_until_complete(
                run_evaluation(dataset, "AION Core", threshold=0.0)
            )
            return score
        except Exception as e:
            print(f"Trial {trial.number} failed: {e}")
            return 0.0
    else:
        # Fallback simulation (Phase 10 legacy) if no dataset is found
        print(f"Trial {trial.number}: Dataset not found, using simulation mode.")
        time.sleep(1)
        dummy_accuracy = 0.5 + (0.5 * (1.0 - temperature))
        dummy_latency_penalty = (max_tokens / 4096.0) * 0.1
        return dummy_accuracy - dummy_latency_penalty

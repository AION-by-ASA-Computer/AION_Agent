---
sidebar_position: 4
title: Testing, Profiling & Optimization
description: Guide to the use of the Profiler, Optuna and the Evaluation Harness in AION V3.
---

# Step-by-Step Guide: Testing and Optimization

This guide explains how to use the new AION V3 stack to ensure quality, performance and stability.

## 1. Bottleneck Analysis (Profiling)

If you notice that the agent is slow, follow these steps:

1. **Enable Profiling**: Make sure that `AION_PROFILING_ENABLED=1` is in your `.env`.
2. **Run conversations**: Use the agent normally.
3. **Check the reports**:
   - Go to the Admin Panel (if available) or query the API:
     ```bash
     curl http://localhost:8000/admin/profiling/bottlenecks
     ```
   - The system will tell you if the problem is the LLM, a specific tool or memory retrieval.

## 2. Execution of Quality Tests (Evaluation)

To verify that the agent responds correctly:

1. **Prepare the Dataset**: Use one of the standard datasets in `data/eval_datasets/` or create a new one.
2. **Launch the Evaluation**:
   ```bash
   python -m src.eval.cli --dataset data/eval_datasets/smoke_test.json --threshold 0.8
   ```
3. **Analyze the results**:
   - If the command ends successfully, the agent has passed the threshold.
   - If it fails (exit code 1), a regression was detected.
   - You can see historical details in the database via the `/admin/eval/runs` endpoint.

## 3. Automatic Optimization (Optuna)

To find the best parameters (temperature, max_tokens, memory):

1. **Select the reference dataset**:
   ```bash
   export AION_OPTIMIZER_DATASET=data/eval_datasets/optimization_base.json
   ```
2. **Start the optimization study**:
   ```bash
   python -m src.optimizer.cli --trials 20 --study-name "aion-v3-tuning"
   ```
3. **View the winning parameters**:
   At the end, the script will print the "Best trial".
4. **Explore the graphs**:
   ```bash
   optuna-dashboard sqlite:///data/optuna.db
   ```

## 4. Test-Time Compute (TTC)

For tasks that require "deep reflection":

1. **Invocation**: In the chat, use the prefix `/ttc`:
   ```text
   /ttc Write a custom encryption algorithm and analyze its vulnerabilities.
   ```
2. **Monitoring**: You will see the agent try multiple times to refine the response until it deems it optimal or runs out of budget.
3. **Configuration**: Adjust `AION_TTC_MAX_ATTEMPTS` in `.env` to increase or decrease the "patience" of the agent.

## 5. Environment template coverage

Before opening a PR that touches `src/settings.py`, `upgrade_core.py`, or runtime env reads:

```bash
python scripts/check_env_example_coverage.py
```

The script verifies that every `AION_*` key used in `src/` and defaults injected by `scripts/upgrade_core.py` appear in `.env.example` (active line or `# commented` default). Use `--strict` to require active lines only.

After pulling this branch, run `./scripts/upgrade-aion.sh` (or `--docker`) to inject tool-first runtime keys (`AION_STREAM_LOOP_V2`, `AION_MODEL_TOOL_POLICY`, …) and remove deprecated `AION_ARTIFACT_STRATEGY`.

## 6. LLM call audit (agent-step debugging)

With `AION_LLM_CALL_AUDIT=1`, each LiteLLM/vLLM request and response for an agent step is written under `data/diagnostics/llm_calls/<session_id>/step_NNN_<id>.json` with an `index.jsonl` manifest.

```bash
python scripts/audit_llm_calls.py list
python scripts/audit_llm_calls.py show --session <id> --step 3
python scripts/audit_llm_calls.py analyze
```

Useful for diagnosing truncated tool-call JSON, thinking-budget leaks on vLLM Qwen3, and prompt snapshot comparison alongside `AION_PROMPT_DEBUG=1`.

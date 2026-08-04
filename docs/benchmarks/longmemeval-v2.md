---
title: LongMemEval-V2 (Mnemos)
sidebar_position: 3
description: Integration stress test — Mnemos project-scope retrieval over LME trajectories (dev CLI only).
---

# LongMemEval-V2 + Mnemos

[LongMemEval-V2](https://arxiv.org/abs/2605.12493) evaluates whether a memory system can internalize long web-agent trajectories and answer environment-specific questions.

:::caution Scope of this benchmark
This runner tests **Mnemos project-scope FTS/hybrid recall only** — not the full AION memory stack (SQL Query Memory, KHUB RAG, Agent DB). LME trajectories are a poor fit for Mnemos post-it notes; treat this as an **integration stress test**, not a production Mnemos quality score. For Mnemos-native validation use [mnemos-bench.md](./mnemos-bench.md).
:::

:::note CLI only
Benchmarks are not exposed in the admin UI. Run via `python -m src.benchmarks.cli` (see [overview.md](./overview.md)).
:::

## AION adaptation (v1)

| Aspect | Choice |
|--------|--------|
| Tier | **LME-V2-Small** (~100 shared trajectories, ~25M text tokens) |
| Modality | Text observations only (screenshots deferred) |
| Memory backend | Mnemos (`ltm_notes` + FTS wake/recall) |
| Isolation | `tenant=benchmark`, `user=lme_v2_<run_id>`, `project=lme_<run_id>` (per-run scope) |

## Pipeline

1. **Prepare** — download `questions.jsonl`, `trajectories.jsonl`, `haystacks/lme_v2_small.json` from HuggingFace
2. **Ingest** — denoise accessibility trees, detect cross-run UI chrome boilerplate, chunk at line boundaries (~70k notes for 100 trajectories), bulk-insert into Mnemos (`insert_notes_bulk`)
3. **Query** — per question: Haystack agent with profile `benchmark_memory` calls `memory_recall` iteratively (`scope=project`), answers in `\boxed{}`
4. **Score** — the dataset's own `eval_function` per question; aggregates by ability, eval_function family, and latency p50/p95

## Five memory abilities

- `static` — static state recall
- `dynamic` — dynamic state tracking
- `workflow` — workflow knowledge
- `gotchas` — environment gotchas
- `premise` — premise awareness

## Scoring: the dataset's `eval_function`

Every row in `questions.jsonl` declares how it must be graded, e.g.
`norm_phrase_set_match|lower=true|normalize_hyphen=true|strip_punct=true|separators=,;|require_non_empty=true`.
`src/benchmarks/longmemeval_v2/scoring.py` implements those semantics; ad-hoc
substring matching is **not** used, because it produces both false positives
(a partial phrase set scoring 1.0) and false negatives (abstention answers
scoring 0.0 regardless of quality).

| Family | Rows (of 451) | Semantics |
|--------|---------------|-----------|
| `norm_phrase_set_match` | 200 | Split on the declared separators, normalize each phrase, compare as a **set** — a partial answer fails |
| `llm_abstention_checker` | 128 | The question carries a false premise; an LLM grader checks the model **rejects** it. Answering `UNKNOWN` is incorrect |
| `mc_choice_match` | 68 | Single letter `A`–`H`; 11 of these rows use `true`/`false` instead and fall back to literal comparison |
| `llm_gotchas_checker` | 28 | LLM grader for semantic equivalence of free-form advice |
| `norm_phrase_set_match_ordered` | 26 | As above but **order-sensitive** |
| `mc_choice_set_match` | 1 | Set of letters (e.g. `A,B,F`) |

Normalization applies NFKC, unifies Unicode dashes, folds hyphens to spaces,
drops punctuation, collapses whitespace, and lowercases — symmetrically on both
the reference and the prediction.

Two properties are asserted over all 451 gold answers in
`src/test/test_lme_v2_official_scoring.py`: every gold scores 1.0 against itself,
and a nonsense answer never scores 1.0.

:::caution Multimodal rows
29 of the 451 questions ship an `image`. This runner is text-only; with
`AION_LME_V2_SKIP_IMAGE_QUESTIONS=1` (default) they are reported as `skipped_image`
and excluded from accuracy denominators.
:::

## Agent profile

Use `benchmark_memory` (in `config_std/profiles/benchmark_memory.yaml`): Mnemos
native tools only (`mcp_servers: []`), readonly recall during eval
(`AION_MNEMOS_READONLY_TOOLS=1`). Scope binding per run:

- `AION_DEFAULT_TENANT_ID=benchmark`
- `user_id=lme_v2_<run_id>` (via `eval_scope`)
- `project_slug=lme_<run_id>` (via `sql_query_project` on `AgentPipeline.run_stream`)

`apply_benchmark_isolation_env()` disables LTM extraction, wake injection, skill
distillation, and STM pollution for benchmark turns.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AION_BENCHMARK_DATA_DIR` | `data/benchmarks` | Root for datasets and runs |
| `AION_BENCHMARK_VERBOSE` | `1` | Echo detailed benchmark logs to terminal + `debug.jsonl` |
| `AION_LME_V2_TIER` | `small` | `small` (medium = future) |
| `AION_LME_V2_TEXT_ONLY` | `1` | Skip screenshot archives |
| `AION_LME_V2_JUDGE_PROFILE` | `aion_std` | Profile for final QA step |
| `AION_LME_V2_QA_DISABLE_REASONING` | `1` | Set `enable_thinking=false` for Qwen3/vLLM judge calls |
| `AION_LME_V2_SKIP_WAKE` | `1` | Skip Mnemos wake block during QA (reduces unrelated trajectory noise) |
| `AION_LME_V2_UI_LABEL_LIMIT` | `80` | Max non-menuitem labels per state (menuitems always kept) |
| `AION_LME_V2_NOTE_MAX_CHARS` | `480` | Cap each ingested note (Mnemos `CONTENT_MAX_CHARS` is 500) |
| `AION_LME_V2_RECALL_LIMIT` | `20` | FTS notes merged per question (boosted query + full text) |
| `AION_LME_V2_LLM_JUDGE` | `1` | Grade `llm_abstention_checker` / `llm_gotchas_checker` rows with an LLM; `0` scores them 0.0 offline |
| `AION_LME_V2_JUDGE_MAX_TOKENS` | `16` | The grader only emits `CORRECT` / `INCORRECT` |
| `AION_LME_V2_JUDGE_TIMEOUT` | `60` | Per-verdict timeout (seconds) |
| `AION_LME_V2_MAX_TRAJECTORIES` | `100` | Haystack trajectories to ingest |
| `AION_LME_V2_MAX_STATES_PER_TRAJ` | `0` | `0` = all states (full retention) |
| `AION_LME_V2_MAX_TREE_CHARS` | `0` | `0` = no per-state tree cap |
| `AION_LME_V2_MAX_CHUNKS_PER_TRAJ` | `0` | `0` = unlimited notes per trajectory |
| `AION_LME_V2_BOILERPLATE_THRESHOLD` | `0.6` | Fraction of states for UI chrome detection |
| `AION_LME_V2_INGEST_BATCH_SIZE` | `500` | Notes per `insert_notes_bulk` transaction |
| `AION_LME_V2_COMPRESS_SCOPE` | `0` | Skip digest compression after ingest (recommended) |
| `AION_LME_V2_AGENT_PROFILE` | `benchmark_memory` | Haystack profile for query phase |
| `AION_LME_V2_SKIP_IMAGE_QUESTIONS` | `1` | Skip multimodal rows (report `skipped_image`) |
| `AION_MNEMOS_FTS_PHRASE_QUERY` | `1` | Phrase-aware FTS (enabled by benchmark isolation env) |
| `AION_MNEMOS_READONLY_TOOLS` | `1` | Expose only `memory_recall` during benchmark |

Mnemos knobs are snapshotted in each run's `config.json` (`AION_LTM_WAKE_MAX_ROWS`, `AION_MNEMOS_RECALL_LIMIT`, etc.).

## CLI

```bash
# Prepare dataset
python -m src.benchmarks.longmemeval_v2.prepare

# Run benchmark (agent + full ingest defaults applied at runtime)
python -m src.benchmarks.cli run \
  --benchmark longmemeval_v2_small \
  --profile benchmark_memory \
  --config-json '{"max_questions":8,"max_trajectories":100}'
```

### Staged validation runs

Compare `accuracy_by_eval_function` in `metrics.json` after each milestone:

1. `max_questions=8` — smoke after ingest + FTS + agent wiring
2. `max_questions=50` — mid-scale
3. Full 451 questions — omit `max_questions` in config JSON

## Limitations

- Text-only ingest (29 image questions skipped by default)
- Orchestration sidebar tools are still merged by `build_all_tools` even with `mcp_servers: []`
- Full Small tier ingest ~8 min + agent query cost scales with question count

## Results

Each run writes under `data/benchmarks/runs/<run_id>/`:

| File | Contents |
|------|----------|
| `run.log` | All `[phase]` lines (ingest + query + done) |
| `debug.jsonl` | Full per-case trace: prompts, raw LLM, evidence, score_reason |
| `per_case.jsonl` | Compact results (+ `score_reason`) |
| `config.json` | LLM endpoint/model, scope, limits |
| `metrics.json` | Aggregates + `accuracy_by_eval_function` + `image_cases` + `score_reasons` map |

`score_reason` tells you *why* a case failed: `phrase_set_under_answered` (missed
a phrase), `phrase_set_over_answered` (invented one), `phrase_list_mismatch`
(right phrases, wrong order), `mc_mismatch`, `no_choice_letter_found`,
`llm_answered_unknown`, `llm_judge_incorrect`, `llm_judge_error`. The per-case
`score_debug` in `debug.jsonl` also carries `missing_phrases` / `extra_phrases`
and, for reference, the old heuristic verdict under `heuristic`.

Document official runs under `docs/benchmarks/results/` (JSON + REPORT.md exported from `data/benchmarks/runs/<id>/`).

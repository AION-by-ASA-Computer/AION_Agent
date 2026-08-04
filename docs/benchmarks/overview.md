---
title: Benchmarks & Evaluation
sidebar_position: 1
description: Dev-only CLI benchmark harness for Mnemos, agent regression, and LME integration tests.
---

# Benchmarks & Evaluation

Benchmarks are **developer tools only** — they validate memory retrieval, agent regressions, and integration paths during development. They are **not** exposed in the admin UI or customer-facing surfaces.

## Layout

| Path | Purpose |
|------|---------|
| `src/benchmarks/` | CLI harness, runners, metrics |
| `config_std/benchmarks/` | Committed micro datasets |
| `data/benchmarks/` | Downloaded datasets and run artifacts (gitignored) |
| `docs/benchmarks/` | Documentation (this folder) |

## Available benchmarks

| ID | Purpose | Typical runtime |
|----|---------|-----------------|
| `mnemos_bench` | Mnemos recall (smoke: 6, full: 81, adversarial: 48) | seconds–minutes |
| `general_agent` | Agent pipeline smoke via JSON cases | seconds |
| `longmemeval_v2_small` | Integration stress test (Mnemos-only ingest + agent) | minutes–hours |

See [mnemos-bench.md](./mnemos-bench.md) for the primary Mnemos validation suite.

The full dataset is a **regression guard** (expected 100%). The adversarial
dataset is a **work-item tracker**: it targets known weaknesses and currently
scores around 33%. A rising adversarial score is the signal that memory quality
is actually improving — the full dataset can no longer show that.

LongMemEval-V2 is documented in [longmemeval-v2.md](./longmemeval-v2.md) — note it measures **Mnemos project-scope retrieval**, not the full AION memory stack (SQL QM, KHUB RAG, Agent DB).

## CLI

```bash
# Mnemos recall micro-benchmark (recommended for CI)
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --dataset config_std/benchmarks/mnemos_recall.json

# Mnemos full evaluation (81 cases, accuracy_by_category in metrics.json)
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --dataset config_std/benchmarks/mnemos_recall_full.json

# Mnemos adversarial evaluation (48 cases, expected to fail — see mnemos-bench.md)
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --dataset config_std/benchmarks/mnemos_recall_adversarial.json

# Hybrid recall (requires embedding service)
AION_MNEMOS_EMBEDDING_RECALL=1 \
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --dataset config_std/benchmarks/mnemos_recall.json

# General agent smoke
python -m src.benchmarks.cli run \
  --benchmark general_agent \
  --dataset config_std/benchmarks/smoke_agent.json \
  --profile aion_std

# LongMemEval-V2 (integration / stress test)
python -m src.benchmarks.cli prepare-lme
python -m src.benchmarks.cli run \
  --benchmark longmemeval_v2_small \
  --profile benchmark_memory \
  --config-json '{"max_questions":8}'
```

Optional flags:

- `--run-id <id>` — fixed run id (otherwise auto-generated)
- `--config-json '{"max_cases":3}'` — limit cases (mnemos_bench) or questions (LME)

## Artifacts

Each run writes under `data/benchmarks/runs/<run_id>/`:

| File | Contents |
|------|----------|
| `run.log` | Phase lines (ingest / query / done) |
| `per_case.jsonl` | Per-case scores |
| `metrics.json` | Aggregates (`accuracy_overall`, latency, etc.) |
| `debug.jsonl` | Verbose trace (LME runs) |
| `REPORT.md` | Human summary (LME runs) |

Official LME results can be exported to `docs/benchmarks/results/`.

## Mnemos hybrid recall

When `AION_MNEMOS_EMBEDDING_RECALL=1`, `memory_recall` uses **FTS candidates + embedding rerank** (RRF merge). If the embedding service is unreachable or unconfigured, recall **falls back to FTS-only** automatically.

Reuses `AION_EMBEDDING_URL`, `AION_EMBEDDING_MODEL`, `AION_EMBEDDINGS_PROVIDER` (same as SQL Query Memory).

| Variable | Default | Description |
|----------|---------|-------------|
| `AION_MNEMOS_EMBEDDING_RECALL` | `0` | Enable hybrid FTS+embedding recall |
| `AION_MNEMOS_EMBED_ON_BULK` | `0` | Embed notes during `insert_notes_bulk` (slow for large ingests) |
| `AION_MNEMOS_EMBEDDING_MIN_SCORE` | `0.25` | Min cosine similarity for embedding candidates |
| `AION_MNEMOS_EMBEDDING_SCAN_LIMIT` | `300` | Max notes scanned for pure-embedding fallback |
| `AION_MNEMOS_HYBRID_CANDIDATE_MULT` | `3` | FTS candidate pool multiplier before rerank |

## Optuna tuning

Hyperparameter search remains CLI-only:

```bash
python -m src.optimizer.cli --trials 20 --study-name aion-v3-tuning
```

## Legacy eval CLI

```bash
python -m src.eval.cli --dataset config_std/benchmarks/smoke_agent.json --threshold 0.8
```

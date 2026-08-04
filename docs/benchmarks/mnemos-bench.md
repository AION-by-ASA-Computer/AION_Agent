---
title: Mnemos Bench
sidebar_position: 2
description: Dev-only micro-benchmark for Mnemos FTS and hybrid embedding recall.
---

# Mnemos Bench

Mnemos Bench validates **what Mnemos is designed for**: short post-it notes, scoped recall (user / project), and optional hybrid retrieval — not full episodic memory over 100k trajectory chunks.

Use this benchmark in CI and during FTS/embedding tuning. For integration stress tests over large corpora, see [longmemeval-v2.md](./longmemeval-v2.md).

## What it measures

| Axis | Cases |
|------|-------|
| **FTS keyword hit** | Discriminative terms in note content |
| **Phrase query** | Quoted phrases + portal vocabulary |
| **Scope isolation** | User scope does not leak into project scope |
| **Semantic paraphrase** | Hybrid recall (`prefer_hybrid: true`) |
| **Short tokens** | Class, Price, State not dropped by token ranking |
| **Noise rejection** | Boilerplate terms do not dominate results |

## Dataset

| File | Cases | Use |
|------|-------|-----|
| `config_std/benchmarks/mnemos_recall.json` | 6 | CI smoke / quick regression |
| `config_std/benchmarks/mnemos_recall_full.json` | 81 | Full evaluation across 11 categories |

Regenerate the full set after editing `scripts/build_mnemos_recall_full.py`:

```bash
python scripts/build_mnemos_recall_full.py
```

### Categories (full dataset)

| Category | Cases | What it tests |
|----------|-------|----------------|
| `fts_keyword` | 10 | Discriminative keyword retrieval |
| `fts_phrase` | 8 | Quoted phrases and multi-word entities |
| `scope_isolation` | 8 | User vs project scope must not leak |
| `semantic_paraphrase` | 12 | Hybrid recall (`prefer_hybrid: true`) |
| `short_token` | 6 | Short discriminative tokens (State, MFA, v2) |
| `noise_rejection` | 6 | Boilerplate must not dominate results |
| `disambiguation` | 8 | Target note among 6–8 similar notes |
| `numeric_id` | 6 | Tickets, ports, IBAN, build numbers |
| `url_context` | 6 | traj/url/action patterns from agent memory |
| `dense_corpus` | 6 | Target buried in 20+ distractor notes |
| `multi_hit` | 5 | Multiple expected phrases in top-k |

Each case:

1. Inserts `setup_notes` into an isolated scope (`tenant=mnemos_bench`)
2. Calls `recall(query, limit=recall_limit)`
3. Scores 1.0 if `expected_substrings` appear in top results (and optional `forbidden_substrings` absent)

## Run

```bash
# List available benchmarks
python -m src.benchmarks.cli list

# Smoke (CI)
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --dataset config_std/benchmarks/mnemos_recall.json

# Full evaluation (81 cases, ~30–90s FTS-only)
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --dataset config_std/benchmarks/mnemos_recall_full.json

# Full + hybrid embedding (requires AION_EMBEDDING_* configured)
AION_MNEMOS_EMBEDDING_RECALL=1 \
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --dataset config_std/benchmarks/mnemos_recall_full.json

# Subset for quick iteration
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --config-json '{"max_cases":2}'
```

## Expected output

```
[cli] run_id=bench_c35507bb90
[banner] ════════════════════════════════════════════════════════
[banner]   Mnemos Bench — recall@k validation (dev CLI)
[banner]   run_id:    bench_c35507bb90
...
[result]   PASS  fts_keyword_hit  score=1.0  reason=ok  0.26s  hits=['PostgreSQL']
[done]   6/6 passed  (100.0%)  total 2.7s
[done]   artifacts → data/benchmarks/runs/bench_c35507bb90/
[cli] summary: 6/6 passed (100.0%)
```

Results: `data/benchmarks/runs/<run_id>/` — open `REPORT.md` or `metrics.json` for the full breakdown.

## Adding cases

```json
{
  "id": "my_case",
  "scope_type": "user",
  "setup_notes": ["Note text stored in Mnemos"],
  "query": "search terms",
  "expected_substrings": ["Note"],
  "recall_limit": 5,
  "min_hits": 1,
  "prefer_hybrid": false
}
```

Optional scope-leak check:

```json
{
  "negative_scope_type": "project",
  "negative_notes": ["Unrelated project note"],
  "negative_query": "secret token"
}
```

## Relation to production memory

Mnemos is one layer in AION's memory stack:

```
STM (chat window)
Mnemos notes (this benchmark)
SQL Query Memory (embedding + FTS on SQL cache)
Project RAG / KHUB (long documents — future native hook)
Agent DB / MemPalace (structured navigation)
```

Mnemos Bench does **not** replace end-to-end eval of the full stack.

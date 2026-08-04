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
| `config_std/benchmarks/mnemos_recall_full.json` | 81 | Regression guard, expected 100% |
| `config_std/benchmarks/mnemos_recall_adversarial.json` | 48 | Known weaknesses, currently ~33% |

Regenerate a set after editing its generator:

```bash
python scripts/build_mnemos_recall_full.py
python scripts/build_mnemos_recall_adversarial.py
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

## Adversarial suite

The full dataset reached 100% and stopped being informative. Worse, it was
partly measuring the wrong thing: its `semantic_paraphrase` category passed
12/12 with embeddings **disabled**, which means the queries were reusing the
notes' own words rather than paraphrasing them.

The adversarial dataset exists to fail. Every category targets a capability we
believe is weak, and a case that passes is a regression guard rather than a
celebration.

### Categories

| Category | Cases | What it tests |
|----------|-------|----------------|
| `alias_coref` | 8 | Target identified only by an alias (`k8s` → Kubernetes), with sibling distractors sharing every generic word |
| `true_paraphrase` | 8 | Query shares **zero** content tokens with the target (enforced by assertion) |
| `temporal_validity` | 5 | Superseded values must never surface as current, including 3-generation chains |
| `contradiction` | 5 | Two active contradictory notes, no supersede hint — the newer must rank first |
| `recency_rank` | 4 | Identical lexical profile, only `created_at` differs |
| `importance_rank` | 4 | Both notes match, `importance` 5 must outrank `importance` 1 |
| `cross_scope` | 5 | A project note must survive a user scope full of lexical matches |
| `scale_recall` | 4 | Target buried under 400–600 filler notes |
| `precision_noise` | 5 | Filler sharing only stopwords with the query must not be returned |

### Baseline (FTS-only, `AION_MNEMOS_EMBEDDING_RECALL=0`)

| Category | Score | Reading |
|----------|-------|---------|
| `temporal_validity` | 5/5 | Supersede chains resolve correctly — a real strength |
| `scale_recall` | 4/4 | BM25 holds up to 600 notes, sub-second |
| `alias_coref` | 5/8 | Partial, and only where a distractor happened to be weaker |
| `importance_rank` | 2/4 | Coincidental — importance is never read during ranking |
| `true_paraphrase` | 0/8 | No embedding service means literally zero semantic recall |
| `contradiction` | 0/5 | Both notes stay active; insertion order decides |
| `recency_rank` | 0/4 | `created_at` is not a ranking signal |
| `cross_scope` | 0/5 | Project notes never returned |
| `precision_noise` | 0/5 | 9 of 10 returned notes are pure noise |

### Defects confirmed by the suite

Three findings are specific enough to be pinned by unit tests in
`src/test/test_mnemos_known_gaps.py`, each marked `xfail(strict=True)` so that a
fix forces the marker to be removed:

1. **Hard delete leaks into digests.** `forget_note(hard=True)` removes the row
   and the FTS entry but never calls `invalidate_digests_covering`, so the
   content survives in `ltm_digests.summary_text` and keeps reaching the model
   through wake.
2. **Cross-scope starvation.** `recall_across_scopes` fills the result list one
   scope at a time and returns as soon as the limit is reached. With the default
   `AION_MNEMOS_RECALL_LIMIT=10`, a user scope with ten lexical matches makes
   project memory unreachable. Scores are never normalised across scopes.
3. **Stopwords are search terms.** The default query path
   (`AION_MNEMOS_FTS_PHRASE_QUERY=0`) is `_escape_fts_query_legacy`, which ORs
   every token of two characters or more with no stopword filtering. Any note
   sharing an article with the query is returned as a match. The `_FTS_STOPWORDS`
   list exists but is only consulted by the v2 path, and it contains
   LongMemEval boilerplate (`boxed`, `servicenow`, `portal`) rather than common
   English words like `the`, `is`, or `of`.

### Extra dataset fields

The adversarial suite needs expressiveness the original schema lacked. All of it
is backward compatible — the 81-case dataset still runs unchanged.

```json
{
  "id": "recency_budget",
  "category": "recency_rank",
  "scope_type": "project",
  "setup_notes": [
    { "content": "Budget approved at 120000 EUR", "age_days": 540 },
    { "content": "Budget approved at 180000 EUR", "importance": 5 }
  ],
  "query": "budget approved",
  "expected_substrings": ["180000"],
  "expect_top_k": 1
}
```

| Field | Effect |
|-------|--------|
| `setup_notes[].content` | Note body (a plain string is still accepted) |
| `setup_notes[].category` / `.importance` | Written through to the note row |
| `setup_notes[].age_days` | Backdates `created_at` so recency can be exercised |
| `setup_notes[].supersedes` | Index of an earlier note in the same list to supersede |
| `expect_top_k` | Expected substrings must appear within the first N results; a hit outside the window reports `rank_miss` |
| `filler` | `{count, position, template}` — bulk-inserted noise before or after the setup notes |
| `extra_scope_type` / `extra_scope_notes` | Populate a second scope |
| `recall_scope: "across"` | Query via `recall_across_scopes` over both scopes |

Forbidden substrings are checked across **all** returned rows, while expected
substrings are checked inside the `expect_top_k` window.

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

# Adversarial evaluation (48 cases, expected to fail — see above)
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --dataset config_std/benchmarks/mnemos_recall_adversarial.json

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

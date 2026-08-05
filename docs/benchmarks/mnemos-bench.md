---
title: Mnemos Bench
sidebar_position: 2
description: Dev-only benchmark for Mnemos FTS and hybrid embedding recall — smoke, full regression, and adversarial suites.
---

# Mnemos Bench

Mnemos Bench validates **what Mnemos is designed for**: short post-it notes, scoped recall (user / project), and hybrid retrieval — not full episodic memory over 100k trajectory chunks.

Use this benchmark in CI and during FTS/embedding tuning. For integration stress tests over large corpora, see [longmemeval-v2.md](./longmemeval-v2.md).

Architectural context and phase-by-phase improvements: [Mnemos Architectural Hardening](../memory/mnemos-hardening.md).

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
| `config_std/benchmarks/mnemos_recall_full.json` | 81 | Regression guard, expected **100%** |
| `config_std/benchmarks/mnemos_recall_adversarial.json` | 53 | Weakness tracker + post-hardening scorecard |

Regenerate after editing generators:

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

The adversarial dataset targets capabilities that are hard to exercise with keyword-only cases. After the hardening programme it serves as a **scorecard**: rising scores mean memory quality is improving.

### Categories

| Category | Cases | What it tests |
|----------|-------|----------------|
| `alias_coref` | 8 | Target identified by alias (`k8s` → Kubernetes), with sibling distractors |
| `true_paraphrase` | 8 | Query shares **zero** content tokens with the target (assertion-enforced) |
| `temporal_validity` | 5 | Superseded values must not surface as current |
| `as_of_query` | 3 | `recall(as_of=…)` must return facts valid at a past date |
| `deletion_completeness` | 2 | Hard-deleted notes must not appear in recall or wake |
| `contradiction` | 5 | Two active contradictory notes — ranking must prefer the right one |
| `recency_rank` | 4 | Only `created_at` differs between matching notes |
| `importance_rank` | 4 | `importance` 5 must outrank `importance` 1 |
| `cross_scope` | 5 | Project note must survive a crowded user scope |
| `scale_recall` | 4 | Target under 400–600 filler notes |
| `precision_noise` | 5 | Filler sharing only stopwords must not pollute results |

### Current scores (post-hardening)

| Mode | Overall | Key categories |
|------|---------|----------------|
| **FTS-only** (`AION_MNEMOS_EMBEDDING_RECALL=0`) | **40/53 (75.5%)** | `precision_noise` 5/5, `cross_scope` 5/5, `recency_rank` 4/4, `true_paraphrase` 0/8 |
| **Hybrid** (default, embeddings on) | **46/53 (86.8%)** | `true_paraphrase` 8/8, `alias_coref` 7/8, `precision_noise` 0/5 |

Hybrid mode requires `AION_EMBEDDING_URL` + `AION_EMBEDDING_MODEL` configured. Use `AION_MNEMOS_EMBED_ON_BULK=1` when running the adversarial suite with hybrid so filler notes receive vectors.

**Trade-off:** hybrid recall improves paraphrase and alias resolution but can surface semantically similar filler notes (`precision_noise` regression). See [known trade-offs](../memory/mnemos-hardening.md#known-trade-offs).

### Regression guards

Fixed defects are covered by normal (non-xfail) tests in `src/test/test_mnemos_known_gaps.py`:

1. Hard delete purges covering digests and wake skips stale digest blocks.
2. Cross-scope recall merges all scopes with global ranking.
3. FTS queries exclude English/Italian stopwords from the default path.

### Extra dataset fields

Backward compatible — the 81-case full dataset runs unchanged.

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
| `setup_notes[].content` | Note body (plain string still accepted) |
| `setup_notes[].category` / `.importance` | Written to the note row |
| `setup_notes[].age_days` | Backdates `created_at` for recency tests |
| `setup_notes[].supersedes` | Index of earlier note in the same list to supersede |
| `setup_notes[].valid_from` / `.valid_to` | Bi-temporal validity (ISO-8601) |
| `as_of` | Passed to `recall(as_of=…)` |
| `expect_top_k` | Expected substrings must appear in top N; else `rank_miss` |
| `filler` | `{count, position, template}` — bulk noise before/after setup |
| `extra_scope_type` / `extra_scope_notes` | Second scope for cross-scope cases |
| `recall_scope: "across"` | Uses `recall_across_scopes` |
| `hard_delete_index` | Hard-delete a setup note before recall/wake check |
| `wake_forbidden_substrings` | Fail if substring appears in wake output |
| `min_hits: 0` | Pass on absence of forbidden hits only (deletion cases) |

Forbidden substrings are checked across **all** returned rows; expected substrings inside the `expect_top_k` window.

## Run

```bash
# List available benchmarks
python -m src.benchmarks.cli list

# Smoke (CI)
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --dataset config_std/benchmarks/mnemos_recall.json

# Full regression (81 cases, must stay 100%)
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --dataset config_std/benchmarks/mnemos_recall_full.json

# Adversarial scorecard (53 cases)
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --dataset config_std/benchmarks/mnemos_recall_adversarial.json

# FTS-only baseline (explicit)
AION_MNEMOS_EMBEDDING_RECALL=0 \
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --dataset config_std/benchmarks/mnemos_recall_adversarial.json

# Hybrid (default in .env.example; requires AION_EMBEDDING_*)
AION_MNEMOS_EMBEDDING_RECALL=1 AION_MNEMOS_EMBED_ON_BULK=1 \
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --dataset config_std/benchmarks/mnemos_recall_adversarial.json

# Subset for quick iteration
python -m src.benchmarks.cli run \
  --benchmark mnemos_bench \
  --config-json '{"max_cases":2}'
```

## Expected output

```
[cli] run_id=bench_c35507bb90
[banner]   recall:    hybrid FTS+embedding
[result]   PASS  fts_keyword_hit  score=1.0  reason=ok  0.26s  hits=['PostgreSQL']
[done]   81/81 passed  (100.0%)  total 6.9s
[done]   by category:
[done]     true_paraphrase: 8/8 (100%)
[cli] summary: 46/53 passed (86.8%)
```

Results: `data/benchmarks/runs/<run_id>/` — `REPORT.md`, `metrics.json`, `per_case.jsonl`.

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

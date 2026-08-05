---
sidebar_position: 3
title: Mnemos Architectural Hardening
description: Report on the Mnemos hardening programme — auth, retrieval, provenance, dream cycle, and entity index gate.
---

# Mnemos Architectural Hardening

This document records the architectural improvements delivered in the Mnemos hardening programme. Each phase has measurable exit criteria based on the adversarial benchmark suite (`config_std/benchmarks/mnemos_recall_adversarial.json`). The full regression dataset (`mnemos_recall_full.json`, 81 cases) must remain at **100%**.

## Success metrics

| Suite | FTS-only | Hybrid (embeddings on) | Notes |
|-------|----------|------------------------|-------|
| **Full regression** (81 cases) | 100% | 100% | Must never regress |
| **Adversarial** (53 cases) | **40/53 (75.5%)** | **46/53 (86.8%)** | Target ≥70% after Phase 1; ≥85% with hybrid |

### Adversarial scores by category (after hardening)

| Category | FTS-only | Hybrid | Phase |
|----------|----------|--------|-------|
| `precision_noise` | 5/5 | 0/5 | 1 — hybrid pulls semantic distractors |
| `recency_rank` | 4/4 | 4/4 | 1 |
| `importance_rank` | 4/4 | 4/4 | 1 |
| `cross_scope` | 5/5 | 5/5 | 1 |
| `temporal_validity` | 5/5 | 5/5 | 1 |
| `contradiction` | 5/5 | 5/5 | 1 |
| `as_of_query` | 3/3 | 3/3 | 2 |
| `deletion_completeness` | 2/2 | 2/2 | 1–2 |
| `scale_recall` | 3/4 | 3/4 | 1 |
| `alias_coref` | 4/8 | 7/8 | 4 (gate) |
| `true_paraphrase` | 0/8 | **8/8** | 1.5 — requires embeddings |

`true_paraphrase` is intentionally excluded from FTS-only targets: without an embedding service it cannot pass by design.

---

## Phase 0 — Project authorization

**Problem:** Any authenticated chat user who knew a project slug could read, write, or delete notes on `/v1/project-memory/*` with only `require_chat_auth`.

**Changes:**

- `require_project_access` dependency on all project-memory routes, reusing `sql_query_memory.check_user_project_access`.
- Delete route resolves the project slug from the note row before checking access.
- `delete_project_note(note_id, *, tenant_id, project_slug)` enforces scope consistency.
- Tests: `src/test/test_project_memory_authz.py`.

**Dev caveat:** With `AION_CHAT_PASSWORD_AUTH=0` the identity is anonymous and access control degrades to open — acceptable for local development only.

---

## Phase 1 — Retrieval correctness

### 1.1 FTS precision

- Removed `_escape_fts_query_legacy` and the `AION_MNEMOS_FTS_PHRASE_QUERY` branch.
- Real Italian + English stopword list (not LongMemEval boilerplate tokens).
- Three-level query strategy in `build_fts_queries`: phrase AND → top-3 discriminative terms AND → OR fallback.

### 1.2 Ranking

- `fts_search` returns `(note, bm25_score)` tuples.
- New `src/memory/mnemos/ranking.py`: RRF fusion + recency exponential decay + importance boost.

```text
base = reciprocal_rank_fusion([lexical_ids, embedding_ids, entity_ids?])
recency = exp(-age_days / half_life_days)
final = base × (1 + w_recency × recency + w_importance × (importance - 1) / 4)
```

### 1.3 Cross-scope recall

- `recall_across_scopes` queries **all** scopes, merges ranked lists globally, deduplicates, then truncates — no positional starvation of project memory.

### 1.4 Deduplication

- After supersede-chain resolution, results are deduplicated by terminal note id (best rank kept).

### 1.5 Hybrid recall

- Embedding search always runs when configured; results merge with FTS via RRF (not FTS-gated).
- `python -m src.memory.mnemos.backfill_embeddings` for notes inserted before embeddings were enabled.
- Dream cycle reuses backfill as a nightly phase.

### 1.6 Hard delete

- `forget_note(hard=True)` clears `summary_text` and sets `ready=False` on covering digests.
- `max_seq()` drives wake/compress upper bound instead of row count (fixes seq drift after hard delete).
- Wake skips digest blocks with no active notes in range.

### 1.7 Resource leaks

- `clear_mnemos_turn_context(session_id)` in the agent pipeline `finally` block.
- Per-scope single-flight lock on `schedule_compress`; leaf-only compression on insert; full recompression in dream cycle.

---

## Phase 2 — Provenance and bi-temporality

### Migration `r0s1t2u020`

New columns on `ltm_notes`:

| Column | Purpose |
|--------|---------|
| `confidence` | 0–1 estimate of factual solidity |
| `confidence_source` | e.g. `extraction`, `user_explicit` |
| `valid_from` / `valid_to` | When the fact was / is true |
| `last_recalled_at` / `recall_count` | Usage tracking for decay |
| Index `(tenant_id, scope_type, scope_key, status)` | Scope queries |

### Provenance end-to-end

`user_message_id` and `assistant_message_id` propagate from `agent_pipeline` → `extract_and_persist` → `apply_extraction` → `insert_note` as `source_message_id`.

### Extraction schema

`config_std/skills/ltm_note_extraction.md` adds `confidence` and `valid_from`. Low-confidence notes are wrapped in `~…~` via `format_note_line`.

### Recall and tools

- `mode="current"` filters `valid_to` in addition to supersede chains.
- `recall(..., as_of=datetime)` projects the dataset to a past point in time.
- `memory_note` tool exposes `supersede_hint` for explicit corrections.

---

## Phase 3 — Dream cycle

Nightly maintenance loop (`src/runtime/memory_maintenance.py`), started in the API lifespan alongside `offload_cleanup_loop`.

| Phase | Module | Purpose |
|-------|--------|---------|
| Compress | `compress_all_pending()` | Finish incomplete digests |
| Contradictions | `resolve_contradictions()` | High-similarity pairs → LLM → `supersede_note` |
| Confidence decay | `decay_stale_confidence()` | Reduce confidence on notes not recalled in N days |
| Embedding backfill | `backfill_embeddings()` | Fill missing vectors |
| Metrics snapshot | `snapshot_quality_metrics()` | Active notes, never-recalled fraction, top users |

Manual run:

```bash
python -m src.memory.mnemos.dream --tenant default
```

---

## Phase 4 — Entity index (gate decisional)

**Not a graph** — a mention index seeded from systems of record (projects, MCP registry) plus built-in abbreviation aliases (`k8s`, `pg`, `mfa`, …).

Tables: `ltm_entities`, `ltm_note_entities` (migration `s1t2u3v021`).

**Gate:** Enable with `AION_MNEMOS_ENTITY_RECALL=1` only when `alias_coref` stays below 6/8 after Phases 1–3. At hybrid 86.8%, `alias_coref` is 7/8 — entity recall is optional.

Entity matches contribute a third RRF rank list in `recall`. `split_entity()` supports undoing a bad merge.

---

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `AION_MNEMOS_EMBEDDING_RECALL` | `1` | Hybrid FTS + embedding RRF |
| `AION_MNEMOS_EMBED_ON_BULK` | `1` | Embed during bulk insert (set `0` for huge one-shot imports) |
| `AION_MNEMOS_EMBEDDING_MIN_SCORE` | `0.25` | Min cosine for embedding candidates |
| `AION_MNEMOS_EMBEDDING_SCAN_LIMIT` | `300` | Max notes scanned per scope (needs vector index beyond ~5k) |
| `AION_MNEMOS_HYBRID_CANDIDATE_MULT` | `3` | FTS/embedding candidate pool multiplier |
| `AION_MNEMOS_RANK_HALF_LIFE_DAYS` | `90` | Recency decay half-life |
| `AION_MNEMOS_RANK_W_RECENCY` | `0.3` | Recency boost weight |
| `AION_MNEMOS_RANK_W_IMPORTANCE` | `0.2` | Importance boost weight |
| `AION_MNEMOS_DREAM_ENABLED` | `1` | Nightly dream cycle |
| `AION_MNEMOS_DREAM_HOUR` | `3` | UTC hour for dream run |
| `AION_MNEMOS_DREAM_INTERVAL_SEC` | `86400` | Loop interval |
| `AION_MNEMOS_ENTITY_RECALL` | `0` | Optional entity RRF signal (gate) |
| `AION_MNEMOS_CONFIDENCE_DECAY_DAYS` | `90` | Dream: days before confidence decay |
| `AION_MNEMOS_CONFIDENCE_DECAY_FACTOR` | `0.9` | Multiplier per decay cycle |
| `AION_MNEMOS_CONFIDENCE_MIN` | `0.2` | Floor for confidence |

Embedding service reuses `AION_EMBEDDING_URL`, `AION_EMBEDDING_MODEL`, `AION_EMBEDDINGS_PROVIDER`. If unconfigured or unreachable, recall **falls back to FTS-only** automatically.

---

## Upgrade and setup

`scripts/upgrade-aion.sh` (and `setup_core.py`) call `_ensure_mnemos_env_keys`:

- Appends missing Mnemos keys from defaults.
- Migrates existing `AION_MNEMOS_EMBEDDING_RECALL=0` → `1`.

Production databases need Alembic:

```bash
alembic upgrade head
```

Tests and benchmarks without Alembic use `store.ensure_ltm_schema()` for idempotent column/table creation.

---

## Known trade-offs

1. **Hybrid vs precision:** Semantic recall improves paraphrase and alias resolution but can surface filler notes that share topical similarity (`precision_noise` 0/5 with hybrid). Mitigation options: conditional hybrid, higher cosine threshold, or FTS-first gating for noisy scopes.
2. **Embedding scan window:** `scale_semantic` fails when the target sits outside the last 300 notes by `seq` in a scope with 600+ filler notes. Production scopes above ~5k notes need `sqlite-vec` or similar.
3. **Entity index:** Optional; enable only when alias resolution remains insufficient after hybrid recall.

---

## Related files

| Area | Path |
|------|------|
| Store / FTS / hard delete | `src/memory/mnemos/store.py`, `fts.py` |
| Ranking | `src/memory/mnemos/ranking.py` |
| Recall | `src/memory/mnemos/recall.py` |
| Dream cycle | `src/memory/mnemos/dream.py`, `src/runtime/memory_maintenance.py` |
| Entity index | `src/memory/mnemos/entities.py` |
| Project auth | `src/api/v1/project_memory.py` |
| Tripwire tests | `src/test/test_mnemos_known_gaps.py` |
| Benchmarks | [mnemos-bench.md](../benchmarks/mnemos-bench.md) |

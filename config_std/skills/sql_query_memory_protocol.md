---
name: sql_query_memory_protocol
description: QueryMemory SQL — reuse validated SELECT queries per project (any relational engine).
---

# SQL QueryMemory Protocol

**Canonical guide:** `datasource_memory_protocol` (SQL layer + MemPalace navigation pairing).

**Scope:** analytical **SELECT** on relational databases. **Never** PromQL tools (`search_known_query`, `save_successful_query`).

## Flow

1. `sql_memory_search` / `search_known_sql` for the active project.
2. Reuse hits (score ≥ 0.8 or verified); avoid broad schema dumps unless cache is empty.
3. Execute via the profile toolbox (`toolbox-postgres`, `toolbox-mysql`, …).
4. `sql_memory_save` / `save_successful_sql` with `is_verified=true` only after a correct business answer.

## Do not save

Schema-only probes, failed SQL, or trivial duplicates.

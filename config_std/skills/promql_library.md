---
name: promql_library
description: PromQL patterns, label discipline, and reuse via QueryMemory when available.
tags: [prometheus, promql, observability]
status: verified
source: curated
version: 2
---

# PromQL Library (Patterns)

## Label hygiene
- Prefer **`job`**, **`instance`**, or explicit selectors the user named; avoid unscoped `rate()` over entire metrics.
- When the user names a host or service, include matching labels (e.g. `{instance="..."}`) **when those labels exist** on the series.

## Common patterns
- **CPU**: `rate(process_cpu_seconds_total[5m])`
- **Memory / RSS**: process or cgroup metrics available in the target scrape
- **HTTP errors**: `rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])`
- **Availability**: align windows with SLO definitions the user provides

## QueryMemory — PromQL Cache (**memory** MCP)
> **Scope**: strictly PromQL queries — never general conversation or fact lookup.
- **`search_known_query`**: search the PromQL cache **before** writing any new query from scratch. Uses cosine similarity on embeddings.
- **`save_successful_query`** / **`mark_query_as_successful`**: persist a verified PromQL expression for future reuse.
- Do **not** use `session_search` here — it searches raw chat history (STM), not the PromQL cache.

## Anti-patterns
- Wide `topk()` without filters on large cardinalities.
- Mixing incompatible `rate()` intervals without stating why.

## Session charts (`render_chart` MCP)

The **`render_chart`** tool on the **charts** MCP server (not Prometheus) handles chat chart rendering (`GET /sessions/{id}/charts`). It can render Prometheus metrics (put the PromQL query in `query` and omit `data`) or inline tabular data (fill the `data` array).

For details, usage examples, and layout contracts, see the **`charts_generation`** skill and full documentation in `docs/api-and-runtime/session-charts.md`.

---
name: infra_audit
description: Incident review, dashboard literacy, and evidence-before-conclusions for SRE work.
tags: [sre, observability, incident]
status: verified
source: curated
version: 1
---

# Infrastructure Audit & Incident Discipline

## Before stating root cause
1. Confirm **time range** and **environment** (cluster, namespace, job) match the user’s question.
2. Correlate: metrics ↔ logs ↔ deployments ↔ Grafana annotations when tools allow it.
3. Prefer **observed signals** over guesses; label unknowns explicitly.

## Grafana-oriented checks
- Identify the panel’s query, refresh interval, and whether data is partial or stale.
- Note annotations (deploys, incidents) overlapping the anomaly window.

## Post-incident / audit tone
- Separate **facts** (queries, values, timestamps) from **hypotheses**.
- Give a short **next verification step** if evidence is incomplete.

## Anti-loop
- One hypothesis path at a time; do not re-query identical ranges without a changed parameter.

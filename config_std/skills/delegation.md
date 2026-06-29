---
name: delegation
description: When and how to delegate to an isolated subagent via aion_subagents MCP.
tags: [orchestration, delegation, multi-agent]
status: verified
source: curated
version: 1
---

# Delegation Protocol

## Preconditions
- Use **only** when your profile includes **`aion_subagents`** MCP.
- Do not delegate if the task is a single tool call or a short answer you can do inline.

## When to delegate
- Long-running or **high-isolation** work (e.g. heavy exploration, unrelated codebase subtree).
- Explicit user request for a separate “specialist pass” with its own context budget.

## Handoff quality
- Provide **goal**, **constraints**, **inputs** (paths, IDs, time ranges), and **expected artifact format**.
- Specify **stop conditions** (what “done” means).

## After delegation
- Integrate subagent results into a coherent reply; do not dump raw logs without synthesis.
- Prefer one delegation round; avoid fan-out loops unless the user approves.

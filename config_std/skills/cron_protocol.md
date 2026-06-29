---
name: cron_protocol
title: Scheduled jobs (cron)
description: Create and manage recurring agent tasks via built-in cron tools.
sidebar_position: 90
tags: [automation, cron, schedule]
---

# Scheduled jobs

Use built-in **cron** tools (not MCP) to run prompts on a schedule for the **current user**.

## Tools

| Action | Tool |
|--------|------|
| Create | `create_scheduled_job` |
| List | `list_scheduled_jobs` |
| Details | `get_scheduled_job` |
| Update | `update_scheduled_job` |
| Delete | `delete_scheduled_job` |
| Pause / resume | `pause_scheduled_job` / `resume_scheduled_job` |
| Run now | `run_scheduled_job_now` |

## Cron expression

Standard **5 fields**: `minute hour day month weekday` (e.g. `0 9 * * 1` = every Monday 09:00).

## Session mode

- **fixed** — same conversation each run (context accumulates).
- **new** — new conversation every run.

## Rules

- Jobs belong to the current user only.
- Requires server `AION_CRON_ENABLED=1`.
- Prefer clear `name` and `prompt` describing the recurring task.

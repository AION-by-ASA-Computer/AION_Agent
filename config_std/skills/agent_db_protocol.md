---
name: agent_db_protocol
description: When and how to use Agent DB (per-user SQLite) for persistent structured data.
tags: [database, ltm, structured-data, sql]
version: 3
---

# Agent DB Operational Protocol

`agent_db_*` manages user-isolated tabular data (`user_id`, `tenant_id`). It is not corporate PostgreSQL.

## Context parameters
- `user_id`, `tenant_id`, and `conversation_id` are runtime-injected if omitted.
- Use `schema_name` when querying logical table names.

## Recommended sequence
1. `agent_db_list_schemas`
2. `agent_db_describe_table`
3. `agent_db_create_table` (if needed)
4. `agent_db_insert_batch(validate_only=true)`
5. `agent_db_insert_batch(validate_only=false)`
6. `agent_db_query` for verification
7. `agent_db_export` when needed

## Anti-loop rules
- Do not repeat identical tool calls.
- At most one corrected retry after failure.
- If retry fails, stop and report clear error + next step.
- Do not expose internal chain-of-thought.

## Strict input format
- `agent_db_create_table.columns` must be a JSON array.
- `agent_db_insert_batch.rows` must be an array of JSON objects.
- No markdown/code-wrapper formatting inside tool arguments.

## Language
Reply in the same language used by the user unless explicitly requested otherwise.

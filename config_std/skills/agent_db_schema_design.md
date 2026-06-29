---
name: agent_db_schema_design
description: User schema/table design guidelines for Agent DB.
tags: [schema, design, database]
version: 3
---

# Agent DB Schema Design

- Use logical schemas (`schema_name`) to group related tables.
- Prefer snake_case and plural table names.
- Use stable column types; document controlled values clearly.
- Evolve schemas with `agent_db_alter_table` instead of destructive rebuilds.
- Reply in the same language used by the user unless explicitly requested otherwise.

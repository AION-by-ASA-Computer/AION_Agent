---
sidebar_position: 4
title: SOUL, MEMORY and USER
description: Optional files to enrich the system prompt. SOUL and MEMORY are deprecated (replaced by YAML profiles and MemPalace); USER remains active.
---

# SOUL, MEMORY and USER -- optional context layer (legacy)

> :::caution SOUL and MEMORY are deprecated
> The content of **SOUL.md** has been replaced by the **YAML profiles** system (`config/profiles/*.yaml`) with the fields `instructions`, `skills`, `mcp_servers`. The content of **MEMORY.md** has been replaced by **MemPalace** (LTM with knowledge graph, semantic search) and **SQL QueryMemory**.
>
> **USER.md** remains the only layer still active and recommended.
>
> The code for SOUL and MEMORY still exists and is backward-compatible (by setting `AION_SOUL_MEMORY_USER_SPLIT=1`), but it is no longer the recommended path.
> :::

This page describes the **additional layer** of text that can be concatenated to the **system prompt**, in addition to what is defined in the **`config/profiles/*.yaml`** profiles. It does not replace the YAML: it enriches the prompt with **Markdown** content stored on the filesystem.

## Relationship with YAML profiles

| What | Where | Status | Role |
|------|------|-------|-------|
| **Agent profile** | `config/profiles/<slug>.yaml` | **Main** | Name, description, **`instructions`**, **skill** list, **MCP**. It remains the main configuration and versionable in git. |
| **SOUL** | `SOUL.md` | **Deprecated** | Identity and guidelines. Replaced by `instructions` in the YAML profile. |
| **MEMORY** | `MEMORY.md` | **Deprecated** | Operational memory. Replaced by MemPalace (LTM) + SQL QueryMemory. |
| **USER** | `USER.md` | **Active** | Preferences for a single user. The only file layer still recommended. |

The profile **slug** coincides with the YAML file name without extension (e.g. `generic_assistant` from `generic_assistant.yaml`). It is the same value used in `AgentProfile.slug` and in `ProfileMemoryBundle`.

## Activation

The whole mechanism is governed by an environment variable:

| Variable | Default in code | Effect |
|-----------|-------------------|---------|
| **`AION_SOUL_MEMORY_USER_SPLIT`** | `0` | If `1`, `true` or `yes` (case-insensitive), the backend reads the files and inserts them into the system prompt. If `0` (default) or absent, the prompt is constructed **only** from role + YAML instructions + skill block. |

Other useful parameters (see also `.env.example` in the root of the repository):

- **`AION_PROFILE_STATE_DIR`** — root for `MEMORY.md`, `USER.md` and `SOUL.md` "in data" (default `data/profiles`).
- **`AION_MEMORY_FILE_MAX_CHARS`**, **`AION_USER_FILE_MAX_CHARS`**, **`AION_SOUL_FILE_MAX_CHARS`** — size limits in characters (validation on write and bundle).
- **`AION_ADMIN_MEMORY_TOKEN`** — if set, the HTTP routes **`/admin/profile-memory/*`** can require `Authorization: Bearer <token>` (see `src/api/admin_profile_memory.py`).

:::note
Enabling the split is a **backward-compatibility** feature. For new projects, use YAML profiles (`instructions`) and MemPalace (LTM) instead of SOUL and MEMORY.
:::

## Semantics of the three files

- **SOUL** (`SOUL.md`) — **Deprecated.** Identity and long guidelines. The `instructions` field in the YAML profile does exactly the same thing, with significant advantages (versionable in git, validated by the schema, composable with skills and MCP). See [Agent Profiles](./profiles.md).
- **MEMORY** (`MEMORY.md`) — **Deprecated.** Profile-level shared memory. Replaced by MemPalace (LTM with knowledge graph, semantic search, structure in wings/drawers/rooms) and SQL QueryMemory (cache of validated SQL queries). See [STM, LTM and QueryMemory Memory](../memory/stm-ltm-and-query.md).
- **USER** (`USER.md`) — **Active.** Preferences and notes **for a single user** (same concept of `user_id` used by API/Chat UI). A separate file for each `(profile_slug, user_id)` pair.

Implementation of reading and paths: **`src/memory/memory_files.py`**. Prompt construction: **`AgentProfile.generate_system_prompt()`** in **`src/agent_profile.py`**.

## Paths on disk

:::note
These paths are maintained for backward-compatibility. They apply only if `AION_SOUL_MEMORY_USER_SPLIT=1`.
:::

### SOUL

The system searches for **the first existing file** among:

1. `config/profiles/<slug>/SOUL.md` — if the `config/profiles/<slug>/` **directory** exists (profile "with folder").
2. Otherwise `data/profiles/<slug>/SOUL.md` (under `AION_PROFILE_STATE_DIR`).

The **write** via admin API goes to:

- `config/profiles/<slug>/SOUL.md` if the profile folder exists;
- otherwise `data/profiles/<slug>/SOUL.md` (creating the directories if necessary).

Functions: `soul_read_path()`, `soul_write_path()` in `memory_files.py`.

### MEMORY

Always:

- `<AION_PROFILE_STATE_DIR>/<slug>/MEMORY.md`  
  (default: `data/profiles/<slug>/MEMORY.md`)

### USER

For sanitized user:

- `<AION_PROFILE_STATE_DIR>/<slug>/<user_id>/USER.md`

`user_id` is normalized by **`sanitize_user_id()`** in `src/identity.py` (safe characters for path). The actual value depends on the client: body/header `user_id` in `POST /chat`, or Chat user (see [Identity and Chat Auth](../security/identity-and-chat-auth.md)).

## Order in the system prompt (split active)

:::note
This order applies only if `AION_SOUL_MEMORY_USER_SPLIT=1` is explicitly enabled (legacy scenario).
:::

With **`AION_SOUL_MEMORY_USER_SPLIT`** enabled, the order of the joined parts is:

1. **SOUL** (file content only; if not empty, inserted as the **first** block).
2. `# Role: <name>` + **`instructions`** from the YAML.
3. Skill section (`index` or `full` mode according to `AION_SKILL_SYSTEM_PROMPT_MODE`).
4. If **MEMORY** is not empty → section with heading `## OPERATIONAL MEMORY (agent)`.
5. If **USER** is not empty → section `## USER PREFERENCES`.

If the files do not exist or are empty, the relative parts add nothing: the behavior is equivalent to not having that layer.

## What to use instead of SOUL and MEMORY

### SOUL.md → YAML Profiles

The `instructions` field in the YAML profile (`config/profiles/<slug>.yaml`) does exactly the same thing as SOUL.md, but with significant advantages:

- **Versionable in git** (YAML file, not scattered markdown)
- **Validated** by the schema (`ProfileSchema`)
- **Composable** with skills and MCP servers
- **Automatically loaded** by the `ProfileManager`

Example:

```yaml
# config/profiles/my_profile.yaml
name: My Profile
instructions: |
  You are an expert assistant for X.
  Your tone is professional but friendly.
  Follow these guidelines:
  - ...
```

See [Agent Profiles](./profiles.md) for full details.

### MEMORY.md → MemPalace + QueryMemory

MemPalace offers a much richer long-term memory:

- **Knowledge graph** (nodes and relations between entities)
- **Semantic search** (Chroma embeddings)
- **Structure organized** in wings, drawers, rooms
- **Automatic extraction** LLM post-turn

SQL QueryMemory adds a cache for validated SQL/SELECT queries, separate from the PromQL system.

See [STM, LTM and QueryMemory Memory](../memory/stm-ltm-and-query.md) for full details.

### USER.md → Remains active

USER.md remains the only recommended file layer. It works as described on this page.

## Runtime integration

1. **`get_agent(profile_name, session_id, user_id)`** (`src/main.py`) loads the profile and calls **`profile.generate_system_prompt(user_id)`**.
2. With active split, **`ProfileMemoryBundle(profile.slug, user_id)`** is created and **`snapshot()`** reads the three files.
3. The same `user_id` is propagated where needed (MCP, context, etc.) — consistency with the `USER.md` path.

For **direct APIs**: `POST /chat` accepts `user_id` in the JSON and/or the **`X-AION-User-Id`** header (priority to the header if present), as in [REST API and contract](../api-and-runtime/rest-api.md).

## Management from Admin UI and REST API

- **Interface:** Next.js app **`admin-ui/`**, route **`/profile-memory`** — the SOUL and MEMORY tabs are considered legacy (their content is copied into the YAML profiles and MemPalace respectively). The USER tab remains active and recommended.
- **API:** prefix **`/admin/profile-memory/`** — e.g. `GET/PUT .../<slug>/soul`, `.../memory`, `GET .../<slug>/users/<user_id>` for USER, `GET .../<slug>/meta` for metadata and limits.

If **`AION_ADMIN_MEMORY_TOKEN`** is set, requests must include the expected bearer token from the backend.

Memory Hub (**`/memory`** in the admin UI) instead concerns **PromQL query cache** and **MemPalace (LTM)** — a separate concept from SOUL/MEMORY/USER; see [STM, LTM and QueryMemory Memory](../memory/stm-ltm-and-query.md).

## What changes compared to "YAML only"

| Scenario | Effect |
|----------|---------|
| Split **off** (default) | None of the three files is read. The prompt is constructed only from role + YAML instructions + skill. |
| Split **on** | SOUL/MEMORY/USER are read and inserted into the prompt. **Not recommended**: use YAML profiles and MemPalace instead of SOUL and MEMORY. |
| Only USER active | Set `AION_SOUL_MEMORY_USER_SPLIT=1` but leave SOUL.md and MEMORY.md empty/absent. |

## References in the code

| File | Content |
|------|-----------|
| `src/agent_profile.py` | `generate_system_prompt()`, condition on `AION_SOUL_MEMORY_USER_SPLIT`. |
| `src/memory/memory_files.py` | `ProfileMemoryBundle`, `BoundedMemoryFile`, paths SOUL/MEMORY/USER. |
| `src/api/admin_profile_memory.py` | REST CRUD and meta routes. |
| `admin-ui/app/profile-memory/page.tsx` | Edit UI. |

## Related documents

- [Agent Profiles](./profiles.md) — **Replace SOUL.md** with `instructions` in the YAML profile.
- [STM, LTM and QueryMemory Memory](../memory/stm-ltm-and-query.md) — **Replace MEMORY.md** with MemPalace (LTM) and SQL QueryMemory.
- [Skills and system prompt](./skills-and-prompts.md) — skill mode `index` / `full` in the same prompt.
- [Identity and Chat Auth](../security/identity-and-chat-auth.md) — `user_id`, login, alignment with `USER.md`.
- [REST API](../api-and-runtime/rest-api.md) — `POST /chat` and system prompt construction.
- [Environment](./environment.md) — overview of variables (cross-reference with `.env.example`).

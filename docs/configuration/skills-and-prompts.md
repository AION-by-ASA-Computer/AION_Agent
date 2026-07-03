---
sidebar_position: 3
title: Skills and system prompt
description: Index/full modes, skill registry and MCP skills_hub.
---

# Skills and system prompt

## Two modes of skill injection

Controlled by **`AION_SKILL_SYSTEM_PROMPT_MODE`**:

- **`index`** (default): in the system prompt only the **name, description and tags** of the profile's skills appear. The full Markdown body is not concatenated (greatly reduces tokens).
- **`full`**: “legacy” behavior: every profile skill is attached in its entirety after the instructions section.

The construction takes place in **`AgentProfile.generate_system_prompt()`** (`src/agent_profile.py`), used by **`get_agent()`** in `src/main.py`.

**Model routing:** `src/runtime/system_prompt.py` merges fragments from `config_std/prompts/` (`default.txt`, `gpt.txt`, `anthropic.txt`, `qwen_vllm.txt`) based on provider/model id. Disable with `AION_MODEL_PROMPT_FRAGMENTS=0`.

Extended tool descriptions for sandbox write/edit/patch live in `config_std/tool_descriptions/` (loaded via `load_tool_description()` when wiring MCP descriptions).

## Skill file format

Skills are **Markdown** files with **YAML frontmatter** (`python-frontmatter`):

Typical fields:

- `name`: unique slug (default: file stem).
- `description`: brief text for the index in `index` mode.
- `tags`: list of strings.
- `status`: e.g. `verified` or `draft`.
- `source`: `curated` (under `config/skills/`) or `generated` (under `data/skills/generated/`).
- `version`: integer; in case of slug duplicates, the highest version wins.

**Directories:**

- `config_std/skills/*.md` — Templates of "curated" skills (versioned in Git).
- `config/skills/*.md` — Active skills loaded by the agent (populated from `config_std` or created locally).
- `config/public_skills.yaml` — (New) Configuration for integrating skills coming from external/public sources.
- `data/skills/generated/*.md` — Automatically proposed skills (distill); directory ignored by Git.

The registry is **`SkillRegistry`** in `src/skill_registry.py` (`skill_registry` singleton). Useful methods: `list_summaries()`, `get_skill_full()` / `get_skill()`, `search()`, `reload()`.

## Progressive disclosure and MCP `skills_hub`

With **`index`** mode, the agent must load the full text or manage its own skills via MCP tools on the **`skills_hub`** server (see `config/mcp_registry.yaml` and `mcp_servers/skills_hub/server.py`):

| Tool | Purpose |
|------|--------|
| `skill_search` | Text search on name/description/tags (limited to the skills of the active profile when `AION_CURRENT_PROFILE_SLUG` is set on the MCP subprocess) |
| `skill_view` | Returns the Markdown body; for skills with a `scripts/` folder, **materializes** the assets in the session (`AION_CHAT_SESSION_ID`). At the end, the **AION skill assets** footer appears. With `AION_SKILL_VIEW_ENFORCE_PROFILE=1` (default) it is allowed only for skills listed in `profile.skills` (gate in `mcp_servers/skills_hub/server.py` + `src/runtime/skill_profile_gate.py`) |
| `skill_list` | List of name + description of the skills **of the active profile** (if enforce active) |
| `sandbox_materialize_skill_scripts` | (session_sandbox) Manual re-sync of skill scripts in the session |
| `skill_save` | Creates or updates an AION skill with YAML frontmatter (saves in `data/skills/generated/` for company sharing or `config/skills/` for permanence) |
| `skill_delete` | Physically deletes a skill from the filesystem and removes it from the registry |

### Profile allowlist on read (`AION_SKILL_VIEW_ENFORCE_PROFILE`)

- **Default:** `1` in `.env.example` and `env` of the `skills_hub` server in `config_std/mcp_registry.yaml`.
- **Effect:** `skill_view` / `skill_list` respect `skills:` of the profile (`AION_CURRENT_PROFILE_SLUG` on the MCP subprocess). Example: `db_navigation_map` can remain in `config/skills/` as a seed file but **not** be readable by `postgres_metadata_assistant` if removed from the profile.
- **Disable (dev only):** `AION_SKILL_VIEW_ENFORCE_PROFILE=0`.
- **Deploy:** after updates to `mcp_servers_std/skills_hub`, run `python scripts/sync_mcp_servers.py --force` and restart the backend.

### Security and Write Gating (`AION_SKILL_WRITE_ENABLED`)

To prevent unauthorized or accidental execution of writing and removing skills by the agent, the `skill_save` and `skill_delete` tools are protected by a gating mechanism at the MCP server level:
- **Configuration**: The `AION_SKILL_WRITE_ENABLED` environment variable (default `"1"`) must be declared specifically under the `env` section of the `skills_hub` server inside `config/mcp_registry.yaml`.
- **Write Block**: By setting `AION_SKILL_WRITE_ENABLED: "0"`, any attempt by the agent to invoke `skill_save` or `skill_delete` will fail immediately, returning a clear and clean error.

### Skill Sharing at the Organization Level

Unlike the individual MCP credentials of single users, skills constitute the team's collective knowledge asset. Therefore, all skills dynamically generated via `skill_save` are saved in the central folder `data/skills/generated/` and instantly reloaded into the agent's global registry. This allows all users in the organization to immediately benefit from the learned automations.

### Coexistence between MCP Learning (Active) and Asynchronous Distillation (Passive)

Dynamic skills generated in chat coexist perfectly with the automatic background distiller (`SkillDistiller`):
- **Active Learning (Phase S - `skills_hub` MCP)**: The agent autonomously decides to save a skill during its turn. Gated via `AION_SKILL_WRITE_ENABLED` in the `mcp_registry.yaml` file.
- **Passive Learning (Phase B - `SkillDistiller`)**: The server asynchronously analyzes post-turn logs to distill recurring flows without slowing down the response or consuming user tokens. Gated via `AION_SKILL_DISTILL_ENABLED` in the global `.env`.

**Lifecycle P2:** generated skills have `status: draft` until promotion (`POST /admin/skills/{slug}/promote` or button in admin-ui). `skill_search` excludes drafts; `skill_view` records metrics if `AION_SKILL_VIEW_METRICS=1`.

Both modules use the same `SkillRegistry` singleton and both write to `data/skills/generated/`, guaranteeing absolute consistency in real time. For an in-depth analysis of architectural trade-offs, consult the guide on [Hermes Features](../learning/hermes-features.md).

Add `skills_hub` to the profile's **`mcp_servers`** list in `config/profiles/*.yaml`.

### Mandatory discovery (soft)

In `index` mode, the system prompt reminds to invoke `skill_search` → `skill_view` before office tasks or writing files. The pipeline can add an internal turn **nudge** (`src/runtime/skill_discovery_nudge.py`) when the user message mentions documents/courses and the profile exposes `skills_hub`.

Remove `doc_intelligence` from `critical_skills` if the skill does not exist in the registry (phantom slug = no inlined block).


## Frontmatter migration

To add frontmatter to existing flat skills:

```bash
python scripts/migrate_skills_frontmatter.py
```

(Requires `python-frontmatter` installed.)

---
sidebar_position: 1
title: Hermes Features - Philosophy and Trade-offs
description: Why Hermes exists, when to enable/disable each feature, and the architectural rationales.
---

# Hermes Features

## Philosophy of the learning system

**Why Hermes?** Hermes is the name of the agent's "mind" - a system that does not limit itself to responding, but **learns from use**. While a traditional assistant simply executes tasks, the assistant with Hermes:

1. **Learns from patterns:** It recognizes that users often make the same queries.
2. **Becomes more efficient:** It automates repetitive tasks by creating skills.
3. **Guides users:** It suggests features ("nudges") that could be useful.
4. **Adapts:** It modifies itself based on how it is used through hooks and subagents.

The separation into feature gates allows enabling only what is needed through environment variables.

---

## PHASE H: Context Compression

**Module:** `src/memory/context_compressor.py`

### Why compression?

**Problem:** LLM models have token limits (typically 32k-128k). If the context exceeds the limit:
1. **Truncated responses:** `finish_reason=length`.
2. **Costs and Latency:** More tokens = more cost and slower responses.

**Solution:** Compress the context keeping key information through LLM summarization, preserving the last messages intact.

---

## PHASE B: Skill Distillation

**Module:** `src/learning/skill_distiller.py`

### Why skill distillation?
It analyzes tool usage patterns and generates pre-configured skills in `config/skills/generated/`. If the agent repeatedly uses a sequence of tools with similar parameters, Hermes proposes to "distill" this knowledge into a new permanent skill.

The LLM prompt includes a **TOOLS:** section with the sequence `tool_start` / `tool_end` / `tool_error` of the turn (limit `AION_SKILL_DISTILL_TOOL_LOG_MAX_CHARS`, default 8000).

---

## PHASE E: Periodic Nudge

**Module:** `src/learning/nudge.py`
Discrete suggestions that appear periodically to guide the user toward advanced features or tools that they are not using but that could be relevant to the current context.

---

## PHASE M: Approval System

**Module:** `src/security/approval_manager.py`
**DB Table:** `approval_rules`

### Why approval system?
It guarantees security in the execution of sensitive tools (shell, python, file writing).
- **Auto-allow**: For safe tools or already approved rules.
- **Ask**: Explicitly requests the user's intervention via SSE `approval_required`.
- **Smart Learning**: If `AION_APPROVAL_LEARN=1`, the system learns from the user's approvals by creating persistent rules in `aion.db`.

---

## PHASE S: Self-Learning & Dynamic Skill Writing

**Module/MCP Server:** `mcp_servers/skills_hub/server.py`

### Why Self-Learning and Skill Writing?
It allows the agent to progressively learn new flows and consolidate them dynamically by writing or deleting skills through the `skill_save` and `skill_delete` tools of the `skills_hub` MCP server.

- **Shared organizational pool**: To make the intelligence accumulated by the agent a shared asset at the organizational level, all dynamically generated skills are saved in `data/skills/generated/` and made immediately available to all users in the organization.
- **MCP Registry Gating (`AION_SKILL_WRITE_ENABLED`)**: To respect the V8 architecture based on MCP, the security control on these writing tools does not pollute the AION `.env` file, but is isolated within the `env` dictionary of the `skills_hub` server in `config/mcp_registry.yaml`. Setting `AION_SKILL_WRITE_ENABLED: "0"` completely inhibits skill creation and deletion operations for all clients.

### Architectural Rationale: Why Separate Active (Phase S) and Passive (Phase B) Learning?

Even though they operate on the same knowledge database, automatic distillation (`SkillDistiller` - Phase B) and manual writing in chat (`skills_hub` - Phase S) are physically separated for fundamental reasons of performance and security:

1. **Logical Union (Single Source of Truth)**:
   Both modules use the same **`SkillRegistry`** singleton and both read and write in the shared folder `data/skills/generated/`. Any skill passively learned or actively written is instantly visible and usable by both systems and by all users in the organization.

2. **Physical Separation for Performance and Efficiency**:
   - **Active Learning (Phase S - Agent-driven via MCP)**: Occurs during the chat turn. It is guided by the agent's reasoning which explicitly decides to save a useful flow. It is executed in an isolated process via stdio MCP server to prevent unauthorized access to the main server's filesystem.
   - **Passive Learning (Phase B - System-driven asynchronous)**: Occurs in the background in the FastAPI server **after** the response has been sent to the user. This avoids lengthening the latency of the chat turn (the user does not have to wait for the LLM to analyze and process the new skill before receiving the response).

3. **Governance and Administrative Flexibility**:
   By separating configurations, an administrator can set granular policies:
   - *Total Learning*: Both active.
   - *System Control Only*: Enables background asynchronous distillation (`AION_SKILL_DISTILL_ENABLED=1`), but forbids the agent in chat from creating or deleting files during the conversation (`AION_SKILL_WRITE_ENABLED: "0"`).

---

## Hook System and Subagents

**Modules:** `src/runtime/hooks.py`, `src/runtime/subagent_orchestrator.py`
Introduced in V2 to allow extreme extensibility. Hooks allow injecting logic in each phase of the lifecycle (e.g., PII redaction, custom logging, message transformation).

---

## Summary: When to enable what

| Feature | Enable when... | Disable when... | Overhead |
|---------|-------------------|----------------------|----------|
| **Compression** | Long sessions (>50 messages) | Short sessions, maximum precision | +1-2s per turn |
| **Skill Distill** | Many users, repetitive queries | You want total manual control | +1 async LLM call |
| **Nudge** | Support for new users | Expert users, minimalist UI | +1 LLM call every N msg |
| **Approval** | Production, sensitive tools (shell) | Local development environment | Turn block for user input |
| **Dynamic Skill Writing** | You want the agent to learn on its own and save new skills | You want to freeze existing skills | Negligible (gating tool) |

---

## Configuration (V2)

```bash
# PHASE H - Compression
AION_CONTEXT_COMPRESS_ENABLED=1
AION_CONTEXT_COMPRESS_THRESHOLD=0.5
AION_CONTEXT_COMPRESS_MODEL_WINDOW=32768
AION_CONTEXT_COMPRESS_KEEP_LAST=6

# PHASE B - Skill Distill
AION_SKILL_DISTILL_ENABLED=1
AION_SKILL_DISTILL_MIN_TOOLS=5
AION_SKILL_GENERATED_DIR=data/skills/generated

# PHASE M - Approval
AION_APPROVAL_ENABLED=1
AION_APPROVAL_LEARN=1
AION_APPROVAL_CRITICAL_TOOLS=sandbox_execute_python,shell_execute

# PHASE E - Nudge
AION_NUDGE_ENABLED=0
AION_NUDGE_EVERY=15

# PHASE S - Self-Learning & Dynamic Skill Writing (MCP level)
# NOTE: This variable is configured at the MCP registry level in config/mcp_registry.yaml
# inside the 'env' dictionary of 'skills_hub' (and not in the global .env)
# AION_SKILL_WRITE_ENABLED=1
```

---

## Related documents

- [Agent Pipeline](../api-and-runtime/agent-pipeline.md) - Where Hermes integrates
- [REST API v1](../api-and-runtime/rest-api.md) - SSE events for Approval
- [Environment variables](../configuration/environment.md) - Complete list of variables
- [Skills and System Prompts](../configuration/skills-and-prompts.md) - How skills and the skills_hub MCP server work

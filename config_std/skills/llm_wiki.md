---
name: llm_wiki
description: Using QueryMemory (query_memory) and legacy RAG documentation search when those servers are enabled.
tags: [memory, rag, documentation]
status: verified
source: curated
version: 1
---

# Technical Wiki & Document Search

## query_memory (session search)
- Search **first** for validated queries, snippets, and prior session answers before authoring new ones from scratch.
- `session_search` lives on **query_memory**. If it is not in the tool list, call `tool_search("session_search")` first.

## rag (legacy documentation)
- When **rag** MCP is in your profile, use it for **internal or legacy docs** not present in the chat.
- Summarize with citations to retrieved passages; do not invent version-specific APIs without retrieval.

## Ordering
1. User-stated sources → 2. query_memory → 3. rag (if present) → 4. general reasoning with limits stated clearly.

## Session artifacts
- Long extracts belong in workspace artifacts (`artifact_protocol`), not inline flooding.

---
sidebar_position: 1
title: Overview
description: Purpose of the documentation and connection with the AION site.
---

# Introduction

**AION · ASA:** [https://aion-asa.com](https://aion-asa.com)

This documentation describes the **AION Agent** repository: FastAPI API, Haystack pipeline, **MCP** integration, memory (STM/LTM), **Chat UI** client (Next.js), **admin-ui** dashboard (Next.js) and optional learning features (“Hermes”).

## How to read the doc

| Section | Content |
|---------|-----------|
| [Architecture](../architecture/overview.md) | Request flow, modules, [observability](../architecture/observability.md), [testing](../architecture/testing-and-optimization.md) |
| [Configuration](../configuration/environment.md) | `.env`, YAML, skills and USER (SOUL/MEMORY deprecated) |
| [API and runtime](../api-and-runtime/rest-api.md) | FastAPI, `/chat`, pipeline |
| [Client](../clients/chat-ui.md) | Chat UI, [Admin UI](../clients/admin-ui.md) and [SDK & Widget](../clients/sdk-and-widget.md) |
| [Memory](../memory/stm-ltm-and-query.md) | SQLite, FTS, MemPalace, query memory |
| [MCP](../mcp/registry.md) | Registry and connected servers |
| [Security and identity](../security/identity-and-chat-auth.md) | Users, Chat auth, hardening |
| [Learning Hermes](../learning/hermes-features.md) | Context compression, skill distillation, nudge |

## Standards for writers

The rules on file structure, naming and links are in **[Documentation standards](../standard/authoring.md)**.

---
sidebar_position: 5
title: Chat History and FTS Search
description: Unified database, FTS5 full-text search, migrations, and the session_search tool.
---

# Chat History and FTS Search

## Database Structure

The system persists conversation message history and manages the FTS5 (Full-Text Search) index using the centralized unified database.

### Unified Database (Default: `AION_UNIFIED_DB=1`)
In production and standard dev environments, all chat history is stored within the central SQLite database:
- **File:** `data/aion.db` (SQLite)
- **Manager:** `UnifiedHistoryBridge` in [`src/data/history_bridge.py`](../../src/data/history_bridge.py)
- **Primary table:** `messages`
- **Key fields:**
  - `fts_rowid` (PK, INTEGER autoincrement): physical primary key and rowid reference for the FTS5 virtual table.
  - `id` (VARCHAR(64), UNIQUE): public UUID of the message (UUIDv7).
  - `conversation_id` (VARCHAR(64)): corresponds to the client's `session_id`.
  - `created_at` (DATETIME): creation timestamp.
  - `role` (VARCHAR(32)), `content` (TEXT), `reasoning` (TEXT), `tool_name` (VARCHAR(256)), `tool_call_id` (VARCHAR(128)), `promoted_to_ltm` (INTEGER).

---

## STM (Short-Term Memory) Context Loading

During turn execution, the runtime reads the latest messages to construct the active context window for the LLM:
- **`history_manager.get_window(...)`**: retrieves a chronological window of messages, constrained by:
  - `AION_STM_MAX_TURNS` (default: `10` turns)
  - `AION_STM_TOKEN_BUDGET` (default: `null` / calculated dynamically based on model window)
  - Character limit at the raw string level (default: `60000` characters)

When the conversation approaches token limits, **Context Compaction** automatically summarizes old turns and inserts a compact `[AION COMPACTION]` block (see [Context Compaction](./context-compaction.md)).

---

## Transcript Contract (Write $\rightarrow$ Store $\rightarrow$ Read)

Single contract for chat persistence and UI replay (enforced across [`src/data/history_bridge.py`](../../src/data/history_bridge.py) and [`chat-ui/lib/use-conversation-transcript.ts`](../../chat-ui/lib/use-conversation-transcript.ts)):

| Invariant | Rule |
|-----------|------|
| **Turn IDs** | `user_message_id` + `assistant_message_id` fixed at `turn_started`, immutable |
| **Writer** | Only `agent_pipeline` + `TurnPersistence` write assistant/steps/attachments |
| **Step binding** | Every step/attachment in a turn has `message_id = assistant_message_id` |
| **Compaction** | Atomic transaction: delete messages + child steps/attachments + insert summary + recount |
| **Retrieve** | `GET /chat-ui/.../messages` is read-only (no orphan attach, no dedup, no DB backfill) |
| **Client** | Conversation switch = replace transcript; merge only in-stream for the same conversation |

---

## FTS5 — Full-Text Search and Virtual Tables

SQLite supports the **FTS5** extension for fast text searches across past messages. The database implements a virtual table in **External Content** mode (the FTS index references the physical `messages` table to conserve disk space).

### FTS5 Schema for Unified DB (`data/aion.db`)
The database bootstrap ([`src/data/bootstrap.py`](../../src/data/bootstrap.py)) creates the virtual table attached to `fts_rowid`:

```sql
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content,
    conversation_id UNINDEXED,
    tenant_id UNINDEXED,
    role UNINDEXED,
    seq UNINDEXED,
    created_at UNINDEXED,
    content='messages',
    content_rowid='fts_rowid',
    tokenize='unicode61 remove_diacritics 2'
);
```

Three triggers (`messages_ai`, `messages_ad`, `messages_au`) keep the FTS5 index continuously synchronized on every `INSERT`, `DELETE`, and `UPDATE` on the `messages` table.

### Core Search Methods
- **`fts_search(query, limit=15, since_days=30)`**: Asynchronously searches `messages_fts` ordered by relevance score `bm25(messages_fts)`. Includes sanitization and fallback for malformed query syntax.
- **`fts_search_blocking(...)`**: Synchronous wrapper running on a dedicated thread for synchronous tools.
- **`get_turn_context(message_id, window=2)`**: Retrieves adjacent messages around a matching `message_id` to reconstruct the surrounding conversation for synthesis.

---

## MCP Tool `session_search`

Exposed by the **`query_memory`** MCP server ([`mcp_servers/query_memory/server.py`](../../mcp_servers/query_memory/server.py)).

### Parameters
- `query` (string, required): Search phrase or keywords.
- `limit` (integer, default: 5): Maximum number of session matches to return.
- `since_days` (integer, default: 30): Search window in days.
- `summarize` (boolean, default: false):
  - **`true`**: Synthesizes matching excerpts into a concise natural language summary using the LLM.
  - **`false`**: Returns the raw conversational turns with session ID and timestamp.

### Usage Guidelines for LLMs
Use `session_search` **only** when the user explicitly asks to recall past conversations, discussions, or agreements from earlier sessions.

**Do NOT use `session_search` to:**
1. Search durable business facts, rules, or user preferences $\rightarrow$ use native `memory_recall` (Mnemos).
2. Search SQL SELECT queries or data schemas $\rightarrow$ use `sql_memory_search` (SQL QueryMemory).
3. Search PromQL metric queries $\rightarrow$ use `search_known_query` (PromQL QueryMemory).
4. Search information in the current active session $\rightarrow$ already present in STM context.

---

## Testing and Diagnostics

Integrated unit tests for the history contract and FTS bridge:

```bash
# Verify chat-ui history persistence contract
python -m pytest src/test/test_chat_ui_history_contract.py -v

# Verify bridge insertion and update logic
python -m pytest src/test/test_history_bridge_upsert.py -v

# Verify timeline backfill and message sequencing
python -m pytest src/test/test_timeline_backfill.py -v
```

### Related Documentation
- [STM, LTM, and QueryMemory](./stm-ltm-and-query.md)
- [Context Compaction](./context-compaction.md)
- [Mnemos Long-Term Memory](./mnemos.md)

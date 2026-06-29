---
sidebar_position: 2
title: Chat history and FTS search
description: Unified database, FTS5, migrations and session_search tool.
---

# Chat history and FTS search

## Database Structure (Duality)

The system stores the message history and manages the FTS5 (Full-Text Search) index in two alternative ways depending on the environment variable `AION_UNIFIED_DB`:

### 1. Unified Database (Default: `AION_UNIFIED_DB=1`)
In production and by default in dev, the history is consolidated within the agent's centralized database.
- **File:** `data/aion.db` (SQLite)
- **Manager:** `UnifiedHistoryBridge` in [history_bridge.py](src/data/history_bridge.py)
- **Main table:** `messages`
- **Relevant fields:**
  - `fts_rowid` (PK, INTEGER autoincrement): physical primary key and reference for the FTS5 index.
  - `id` (VARCHAR(64), UNIQUE): public UUID of the message (UUID7).
  - `conversation_id` (VARCHAR(64)): corresponds to the client's `session_id`.
  - `created_at` (DATETIME): creation date/time (corresponds to `timestamp`).
  - `role` (VARCHAR(32)), `content` (TEXT), `reasoning` (TEXT), `tool_name` (VARCHAR(256)), `tool_call_id` (VARCHAR(128)), `promoted_to_ltm` (INTEGER).

### 2. Legacy/Fallback Database (`AION_UNIFIED_DB=0`)
Used for backward compatibility or for isolated tests without loading the AION SQL ORM infrastructure.
- **File:** `data/chat_memory.db` (SQLite)
- **Manager:** `ChatHistoryManager` in [history.py](src/api/history.py)
- **Main table:** `messages`
- **Relevant fields:**
  - `id` (INTEGER PK AUTOINCREMENT): integer primary key and reference for the FTS5 index.
  - `session_id` (TEXT), `profile_name` (TEXT), `user_id` (TEXT), `role` (TEXT), `content` (TEXT), `timestamp` (DATETIME), `promoted_to_ltm` (INTEGER).

---

## STM (Short-Term Memory)

During execution, the runtime reads the queue of the last messages to pass them as context to the LLM via:
- **`history_manager.get_window(...)`**: retrieves a chronological window of messages, checking the limits set by:
  - `AION_STM_MAX_TURNS` (default: `10` turns)
  - `AION_STM_TOKEN_BUDGET` (default: `null` / calculated based on the model's window)
  - Character limit at the string level (default: `60000` characters)

Optionally, the **`ContextCompressor`** module (see [Hermes learning features](../learning/hermes-features.md)) reduces the message footprint if the approximate token count exceeds the trigger threshold, inserting a compressed block `[AION COMPACTION]`.

---

## FTS5 — Full-Text Search and Virtual Tables

SQLite supports the **FTS5** extension to allow ultra-fast text searches on past messages. The database implements a virtual table in **External Content** mode (that is, the FTS index indexes the data but references the physical `messages` table to save disk space).

### FTS5 Schema for the Unified DB (`data/aion.db`)
The bootstrap (in [bootstrap.py](src/data/bootstrap.py)) creates the virtual table attached to `fts_rowid`:
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
Three triggers (`messages_ai`, `messages_ad`, `messages_au`) keep the FTS5 index synchronized at each `INSERT`, `DELETE`, and `UPDATE` operation on the `messages` table.

### FTS5 Schema for the Legacy DB (`data/chat_memory.db`)
It is initialized in [history.py](src/api/history.py) attached to the integer autoincrement `id` field:
```sql
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content,
    session_id UNINDEXED,
    profile_name UNINDEXED,
    role UNINDEXED,
    timestamp UNINDEXED,
    content='messages',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
```

### Functions and Methods in the Code
- **`fts_search()`**: Performs asynchronous search on `messages_fts` ordering by relevance score `bm25(messages_fts)`. Includes a fallback in case of syntax errors in the query string.
- **`fts_search_blocking()`**: Synchronous, starts an event loop in a separate thread to support synchronous MCP tools.
- **`get_turn_context()`** / **`get_turn_context_blocking()`**: Retrieves surrounding messages (configurable window defaulting to 2) around a `message_id` to reconstruct the relevant conversation in the synthesis report.

---

## Bootstrap and Schema Migrations

At application startup, the server performs automatic validation and bootstrap steps in [bootstrap.py](src/data/bootstrap.py):
1. **Schema Creation**: `Base.metadata.create_all` is invoked to generate the core ORM tables.
2. **Legacy Migration**: If it detects that the unified database has a `messages` table in which the `id` column is of type `INTEGER` (old schema PK), it automatically performs the migration:
   - Renames the messages table to `messages_legacy`.
   - Creates the new `messages` table with autoincrementing `fts_rowid` and `id` as a UUID string.
   - Copies the messages, prepending the prefix `aionm-` to the old integer IDs.
   - Updates the related tables (`attachments`, `steps`, `feedbacks`).
   - Rebuilds the FTS5 index by running `INSERT INTO messages_fts(messages_fts) VALUES('rebuild')`.

---

## MCP Tool `session_search`

Exposed by the **`memory`** server (source: [server.py](mcp_servers/query_memory/server.py)).

### Parameters
- `query` (string, required): Term or expression to search for.
- `limit` (integer, default 5): Maximum number of results to display.
- `since_days` (integer, default 30): Time interval of the search.
- `summarize` (boolean, default true):
  - **`true`**: Passes the chat excerpts to `complete_text_sync` to generate a conversational summary response in natural language.
  - **`false`**: Returns a raw list of turns (content, session_id and timestamp).

**Usage rule for the LLM model**:
Use `session_search` **only** when the user explicitly asks to remember conversations, agreements, or words spoken in past sessions.
Do not use it to:
1. Search for preferences or stable business facts (use `mempalace_search`).
2. Search for PromQL queries (use `search_known_query`).
3. Search for information in the current session (already in the context window).

---

## Testing and Diagnostics

To verify the functioning of the history and the FTS bridge, integrated unit tests are available:
```bash
# Runs all tests related to the chat-ui history contract
python -m pytest src/test/test_chat_ui_history_contract.py -v

# Runs tests for the insertion and update logic of the unified bridge
python -m pytest src/test/test_history_bridge_upsert.py -v

# Verifies the correct backfill of historical timelines
python -m pytest src/test/test_timeline_backfill.py -v
```

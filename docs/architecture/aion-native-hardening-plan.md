---
title: Hardening plan — native AION backend
sidebar_position: 21
description: Step-by-step operational plan to close the robustness gaps of the native AION backend identified in aion-vs-longrun-assessment.md.
---

# Hardening plan — native AION backend

:::info Design note
Phased implementation plan for hardening the native AION backend (non-destructive compaction, shared circuit breaker, offload cleanup, registry locking, observability). Status: largely implemented — `Message.archived_at`, `src/runtime/tool_circuit.py`, `cleanup_session_offloads()` and the per-session turn locks in `src/runtime/turn_compaction.py` are in the code, and Phase 8 is marked as implemented below; the "no changes applied" remark in the original note predates this.
:::

:::note
Planning document. No changes have been applied to the code.
It derives from [`aion-vs-longrun-assessment.md`](./aion-vs-longrun-assessment.md)
§3.4 and §8.1. Each phase is designed to be implemented and tested in
isolation, behind a feature flag where it makes sense, without blocking the others.
:::

## Guiding principles

1. **Each phase is independent and reversible.** No phase requires the
   others to already be in production.
2. **Feature flag first**: every new behaviour starts behind an env var
   whose default preserves the current behaviour, and is then enabled in
   staging before production.
3. **Follow the patterns already in the repo** instead of introducing new ones:
   the soft-delete needed for compaction (Phase 1) replicates
   exactly the `archived_at` pattern already used for `Conversation`
   (`src/api/v1/conversations.py:157-175`) — it is not a new pattern to
   invent.
4. **Recommended order**: Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 →
   Phase 5 → Phase 6 → Phase 7. Phases 3 and 4 can be swapped with each other
   without problems; all the others have the logical dependencies indicated below.

---



## Phase 0 — Quick fixes (no migration, minimal risk)

**Goal**: remove the two bugs already confirmed by the tests before building
anything else on top of unreliable code.

### 0.1 Fix the Pi config fingerprint

- **File**: [`src/runtime/llm_limits.py`](../../src/runtime/llm_limits.py)
- **Problem**: `pi_runtime_config_fingerprint()` (lines 65-72) does not
change when `AION_CHAT_MAX_TOKENS` is modified without explicitly setting
`AION_LONG_RUN_MAX_TOKENS`, because `resolve_chat_max_tokens(long_run=True)`
(lines 11-31) only reads `settings.long_run_max_tokens`, cached via
`get_settings()`.
- **Steps**:
  1. In `resolve_chat_max_tokens`, when `long_run=True` and
     `settings.long_run_max_tokens is None`, still include the effective
     value of `settings.chat_max_tokens` used as fallback in the part
     returned to the caller (not only internally).
  2. In `pi_runtime_config_fingerprint()` (lines 65-72), compute the hash
     from the **final resolved value** (the one that would actually be
     used for the turn), not from the raw `long_run_max_tokens` field alone —
     so that any input that changes the final result invalidates the fingerprint.
  3. Re-run `src/test/test_llm_limits.py::test_pi_fingerprint_changes_with_max_tokens`
     and check that it passes.
- **Verification**: `python -m pytest src/test/test_llm_limits.py -v`



### 0.2 Move the offload/ledger env vars into `AionSettings`

- **File**: [`src/settings.py`](../../src/settings.py)
- **Problem**: `AION_TOOL_OFFLOAD_*` and `AION_TOOL_LEDGER_*` are read via
direct `os.getenv` in `tool_offload.py`/`tool_ledger.py`, while the rest
of the config goes through `AionSettings` (pydantic, `env_prefix="AION_"`,
see `settings.py:23-28`).
- **Steps**:
  1. Add to `AionSettings` (next to the `tool_calls_max_per_turn` fields
     etc., `settings.py:71-79`) the new typed fields:
  2. In `tool_offload.py` and `tool_ledger.py`, replace the direct reads
     `os.getenv("AION_TOOL_OFFLOAD_ENABLED", ...)` with
     `get_settings().tool_offload_enabled` (the same pattern already used
     elsewhere in the module for other parameters, if present — otherwise import
     `from src.settings import get_settings` as the other
     `runtime/*` modules do).
  3. **Do not remove the `os.getenv` fallback** in the tests if it is already used
     for quick overrides in the tests — check that the existing tests
     (`test_tool_offload.py`, `test_tool_ledger.py`) keep passing
     by mocking `get_settings()` instead of the env vars, or keep
     dual compatibility (pydantic reads the same env vars anyway because
     of the prefix, so in practice the behaviour in the tests does not
     change if they already use `monkeypatch.setenv`).
- **Verification**: `python -m pytest src/test/test_tool_offload.py src/test/test_tool_ledger.py -v`

---



## Phase 1 — Non-destructive compaction (highest priority)

**Goal**: remove the root cause of the reported problem — compaction
today performs a real, irreversible SQL `DELETE` on the
messages. It is replaced with a soft-delete, following exactly the pattern
already in use for `Conversation.archived_at`.

### 1.1 Schema migration

- **New file**: `migrations/versions/<hash>_message_archived_at.py`
(use `alembic revision -m "message archived at"` to generate the correct
header and the `down_revision` pointing to the latest revision — check with
`alembic heads` before creating it; today it seems to be `m5n6o7p015_message_rating_feedback.py`
but this must be confirmed at implementation time).
- **Steps** (modelled exactly on `migrations/versions/f7a8b9c0d001_mcp_credential_mode.py`,
which already uses the "check existing columns before adding" pattern,
useful for SQLite/Postgres compatibility):
  ```python
  def upgrade() -> None:
      bind = op.get_bind()
      cols = _columns(bind, "messages")
      if "archived_at" not in cols:
          op.add_column(
              "messages",
              sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
          )
      if "archived_reason" not in cols:
          op.add_column(
              "messages",
              sa.Column("archived_reason", sa.String(32), nullable=True),
          )  # "mid_turn_compaction" | "emergency_compaction" | "stm_prune"
      op.create_index(
          "ix_messages_conversation_archived",
          "messages",
          ["conversation_id", "archived_at"],
      )

  def downgrade() -> None:
      bind = op.get_bind()
      op.drop_index("ix_messages_conversation_archived", table_name="messages")
      cols = _columns(bind, "messages")
      if "archived_reason" in cols:
          op.drop_column("messages", "archived_reason")
      if "archived_at" in cols:
          op.drop_column("messages", "archived_at")
  ```
- **FTS5 note**: `Message` uses `fts_rowid` as an autoincrement PK tied to
an external FTS5 index (see `src/data/models.py:112-114`). Check in
`src/data/history_bridge.py` how the FTS index is synchronized
(probably SQLite triggers or manual sync) — archived messages
**must remain** in the FTS index so they can still be found by historical
full-text search, so this migration must not touch the
FTS logic, only add the two columns.



### 1.2 ORM model

- **File**: [`src/data/models.py`](../../src/data/models.py) (lines 110-146)
- **Steps**: add to the `Message` class:
  ```python
  archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
  archived_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
  ```



### 1.3 `history_bridge.py` — replace the physical DELETE

- **File**: [`src/data/history_bridge.py`](../../src/data/history_bridge.py)
- **Steps**:
  1. Add a new function next to `_delete_messages_and_children`
     (line 64):
  2. **Do not remove** `_delete_messages_and_children` — it remains useful for
     explicit permanent-deletion paths (e.g. GDPR / a future retention
     policy), but **stop calling it for compaction**.
  3. In the three places that today call `_delete_messages_and_children` for
     compaction/pruning (lines 729, 861, 889 — inside
     `persist_stm_compaction` and the STM pruning function), replace the
     call with `_archive_messages_and_children(session, session_id, pruned_ids, reason="mid_turn_compaction")`
     (or `"stm_prune"` depending on the context).
  4. **Remove/adapt** the calls to `_cleanup_orphan_steps_and_attachments`
     in the places where messages are now archived instead of deleted: the steps/attachments
     of archived messages are no longer "orphans" (the message still
     exists), so that function must only be invoked in the paths that
     still use physical deletion.



### 1.4 Filter archived messages out of all "active" reads

This is the step with the largest surface — `history_bridge.py` has ~10
`select(Message)...` queries. Every query used to build the **active context
for the LLM** or the **history shown in chat-ui** must exclude archived
messages; queries used for **search/audit/FTS** must keep
including them.

- **Steps**:
  1. For each of the occurrences listed below, determine whether it is "LLM/active chat
     context" (→ add `.where(Message.archived_at.is_(None))`)
     or "search/audit" (→ leave unchanged):
     - `history_bridge.py:54` (generic query — check downstream usage)
     - `history_bridge.py:105` (join on `conversation_id`)
     - `history_bridge.py:158`
     - `history_bridge.py:521-523` (already has an explicit `exclude_message_ids`
       filter — a good place to understand the existing filter pattern and
       reuse it)
     - `history_bridge.py:614`
     - `history_bridge.py:676`
     - `history_bridge.py:734` (`fetch_messages_for_compaction` — **this one
       must NOT be filtered**, it must be able to re-read messages already archived
       by previous compactions if a cumulative summary needs to be built)
  2. In [`src/api/history.py`](../../src/api/history.py) and
     [`src/api/v1/conversations.py`](../../src/api/v1/conversations.py)
     (endpoint `get_conversation_messages`, line 178 onwards),
     add an optional parameter `include_archived: bool = Query(False)`
     — by default the UI only sees active messages (behaviour identical
     to today), but an explicit endpoint/parameter allows a future
     "expand compacted history" without new migrations.



### 1.5 No frontend changes in this phase

The visible behaviour in chat-ui stays identical (the compaction
message with `format_compaction_block()` keeps appearing as it does
today) — this phase is purely backend/data. Exposing an
"expand history" UI is discussed as a future extension in **Phase 8**
(strictly outside the backend scope).

### 1.6 Tests

- Extend/create `src/test/test_history_bridge_compaction.py`:
  - Check that after `persist_stm_compaction` the pruned messages have
    `archived_at` set and **have not been deleted from the table**.
  - Check that `get_conversation_messages(include_archived=False)` does not
    return them, while `include_archived=True` does.
  - Check that `fetch_messages_for_compaction` still sees them (to
    allow future cumulative summaries).

---



## Phase 2 — Wire ledger/offload into the mid-turn sync branch

**Depends on**: none (independent of Phase 1, but must be done before
offload is enabled by default in production, otherwise the gap
described in `aion-vs-longrun-assessment.md` §3.1 stays open).

- **File**: [`src/runtime/turn_compaction.py`](../../src/runtime/turn_compaction.py),
function `_sync_compact_head_tail` (lines 701-750).
- **Reference**: replicate what `compact_memory_fallback` already does in
[`src/runtime/compaction/policy.py`](../../src/runtime/compaction/policy.py)
(lines 44-73) for the v2 path.
- **Steps**:
  1. In `_sync_compact_head_tail`, before building the summarization prompt
     for the LLM, import and call (only if enabled):
  2. If `tool_ledger_enabled()`, append `render_ledger_table(session_id)`
     to the transcript passed to the summarizer, in the same format/position
     used in `compaction/policy.py:51-73` (`<tool-trace>` block).
  3. If there are offloaded paths for the session, append an
     `<offloaded-results>` block with `offload_paths_for_session(session_id)`,
     identical to what is done in the v2 path — so the summary generated
     mid-turn keeps the pointers to the offloaded files instead of losing them.
  4. Watch the **token budget** of the summarization prompt: both
     `render_ledger_table` and the list of offloaded paths must be truncated with the
     same criterion already used in `pi_compaction.py:109` (character cap) so as
     not to blow up the cost of the summarization call.
- **Test**: new test in `src/test/test_turn_compaction.py` (create it if it
does not exist) that: offloads a large tool result → forces a mid-turn sync
compaction → checks that the resulting summary message contains
the reference to the offloaded path.

---



## Phase 3 — Native circuit breaker for repeatedly failing tools

**Depends on**: none.

**Goal**: today only the Pi path has a breaker
(`src/runtime/pi_runtime/tool_circuit.py`) against retry loops on identical
errors (`missing_arguments`, `tool_args_truncated`, generated by
`prepare_mcp_tool_arguments` in `src/runtime/mcp_tool_args.py:196` and used
by both paths). The native path (`src/main.py:306-310`) has no
equivalent protection.

### 3.1 Design choice: shared module, not duplicated

Instead of writing a second circuit breaker copied into
`src/runtime/`, **move** `tool_circuit.py` from
`src/runtime/pi_runtime/tool_circuit.py` to `src/runtime/tool_circuit.py`
(shared level, like `tool_offload.py`/`tool_ledger.py`), and have it
used by both paths. This avoids future duplication and is
consistent with how the rest of the offload/ledger infrastructure is already
organized (§3.2 of `aion-vs-longrun-assessment.md` already calls it
"genuinely shared" for the other two modules).

- **Steps**:
  1. `git mv src/runtime/pi_runtime/tool_circuit.py src/runtime/tool_circuit.py`
     (no change to the content in this step).
  2. Update the only existing import in
     `src/runtime/pi_runtime/tool_invoke.py:76-82` (or wherever the module is
     imported) to point to the new path `src.runtime.tool_circuit`.
  3. In `src/main.py`, right after the call to `prepare_mcp_tool_arguments`
     (lines 306-310), add the same pattern already used on the Pi side in
     `tool_invoke.py`:
  4. Check that `session_id` is already available in that scope of
     `src/main.py` (likely, since the tool wrapper already operates per
     session) — if it is not, propagate it from the caller.
  5. Hook `reset_session_circuit(session_id)` to the end of a successfully
     completed native turn (where per-turn state cleanup already happens today
     — look for the point analogous to `clear_context()` used on the Pi side,
     `pi_turn_runner.py:361`, and replicate it in the native path).
- **Note**: this change *also* solves one of the gaps reported for Pi
in `aion-vs-longrun-assessment.md` §4.5.3 (reset not per session) **if**
done properly — make sure `reset_session_circuit` is called in
both paths at the end of the turn, not only in the native one.
- **Test**: move/extend the existing tests (check whether
`src/test/test_pi_tool_circuit.py` only tests imports from `pi_runtime` —
update the import path) and add a native test that checks
that after N identical failures (`AION_TOOL_CIRCUIT_BREAKER_MAX`; rename
the env var from `AION_PI_TOOL_CIRCUIT_BREAKER_MAX` to a neutral name since
it is now shared — with a compatibility fallback on the old name) the native tool
wrapper returns the `circuit_breaker` error instead of retrying.

---



## Phase 4 — Cleanup of offloaded files on session deletion

**Depends on**: none.

- **File**: [`src/api/v1/conversations.py`](../../src/api/v1/conversations.py),
function `delete_conversation` (lines 157-175).
- **Context**: today this endpoint soft-deletes the `Conversation`
(`archived_at`, lines 166-170) and then releases the MCP pool
(`mcp_manager.release_session`, line 174) — but it does not touch the offloaded files
on disk in `data/sessions/<sid>/derived/tool_results/`, contradicting
what is promised in `docs/architecture/context-offloading.md:274`.
- **Steps**:
  1. In `src/runtime/tool_offload.py`, add a public function:
     ```python
     def cleanup_session_offloads(session_id: str) -> None:
         """Remove the offloaded tool-result directory and ledger for a session."""
         base = safe_resolve(session_id, "derived/tool_results")
         if base.exists():
             shutil.rmtree(base, ignore_errors=True)
         ledger_path = safe_resolve(session_id, "_ledger.jsonl")
         if ledger_path.exists():
             ledger_path.unlink(missing_ok=True)
     ```
  2. In `delete_conversation` (`conversations.py:157-175`), after the MCP
     release, call:
  3. **Decision to confirm with the user**: conversation deletion
     today is a soft-delete (`archived_at` on `Conversation`) — if in the future
     users can "restore" an archived conversation, deleting
     the offloaded files immediately makes that restore incomplete (the pointers in the
     summary would point to files that no longer exist). A more
     cautious alternative: **do not delete immediately**, but add a periodic
     cleanup job (cron/scheduled task) that removes `derived/tool_results/`
     only for conversations with `archived_at` older than N days. See the
     question at the end of the document.
- **Test**: `src/test/test_tool_offload.py`, a new case that creates fake
offloaded files, calls `cleanup_session_offloads` and checks that the
directory disappears.

---



## Phase 5 — Lock on the shared mid-turn registry

**Depends on**: none, but must be done carefully after Phase 2 (same file).

- **File**: [`src/runtime/turn_compaction.py`](../../src/runtime/turn_compaction.py),
`_TURN_RUNTIME_REGISTRY` (line 28).
- **Problem acknowledged in the code itself** (comment at lines 26-27): the
dict is shared between the asyncio task of the SSE loop (parent) and the child
task of `agent.run` (child), mutated by both without a lock.
- **Steps**:
  1. Introduce a parallel dict of per-session locks:
     ```python
     _TURN_RUNTIME_LOCKS: Dict[str, asyncio.Lock] = {}

     def _get_turn_lock(session_id: str) -> asyncio.Lock:
         lock = _TURN_RUNTIME_LOCKS.get(session_id)
         if lock is None:
             lock = asyncio.Lock()
             _TURN_RUNTIME_LOCKS[session_id] = lock
         return lock
     ```
  2. Identify **all** the places that read/write `rt["live_messages"]`,
     `rt["extra_tokens"]` or other mutable keys of `_TURN_RUNTIME_REGISTRY[session_id]`
     (grep `_TURN_RUNTIME_REGISTRY\[` and `rt\[` in the file) and wrap them with
     `async with _get_turn_lock(session_id):` — careful: if some of
     these accesses are currently **synchronous** (not in `async def` functions),
     consider whether a synchronous lock (`threading.Lock`) is needed instead of
     `asyncio.Lock`, depending on where the mid-turn code actually runs
     (separate thread for the synchronous Haystack `agent.run` vs asyncio task) — **to
     be verified with a targeted concurrency test before choosing the type
     of lock**; do not assume.
  3. Add cleanup of the lock when the session ends (to avoid leaking
     the `_TURN_RUNTIME_LOCKS` dict with long sessions/many sessions).
- **Test**: a stress test that launches N concurrent tasks mutating the
same `session_id` and checks there are no inconsistent states (final
`extra_tokens` count correct with respect to the expected sum).

---



## Phase 6 — Observability

**Depends on**: ideally after Phases 1-4, so there is something meaningful
to observe.

- **Goal**: make visible (structured logs, not necessarily a
dashboard) the key events that are silent today:
  1. Every time a compaction happens (mid-turn, emergency, fallback),
     log: `session_id`, branch used, number of archived messages, tokens
     before/after, whether ledger/offload were included in the summary.
  2. Every time the native circuit breaker (Phase 3) blocks a retry,
     log at `warning` level with `session_id`/`tool`/`error_code`.
  3. Every time `cleanup_session_offloads` (Phase 4) removes data,
     log how many bytes/files were freed.
- **File**: add structured logging (`logger = logging.getLogger("aion.turn_compaction")`
already exists in `turn_compaction.py:22` — reuse it; create analogous ones,
`aion.tool_circuit` and `aion.tool_offload`, if not already present).
- **Note**: this phase does not require new infrastructure (no new
Prometheus) if `docs/architecture/observability.md` already describes an existing
structured logging system — check that document before introducing
new patterns.

---



## Phase 7 — End-to-end integration tests

**Depends on**: Phases 1, 2, 3, 4 completed.

- **New file**: `src/test/test_native_hardening_integration.py`
- **Scenario to cover** (a single end-to-end test that validates the whole
chain, in addition to the unit tests already listed per phase):
  1. Session with `AION_TOOL_OFFLOAD_ENABLED=1`, `AION_TOOL_LEDGER_ENABLED=1`.
  2. A tool call produces a large result → it is offloaded.
  3. A mid-turn sync compaction is forced (Phase 2 wired in).
  4. Check that: (a) the generated summary references the offloaded path;
     (b) the original messages have a non-null `archived_at` but are still
     present in the table (Phase 1), not deleted; (c) a subsequent "active"
     query (`include_archived=False`) does not return them.
  5. A second identical preflight failure is forced on a write
     tool → check that the native circuit breaker (Phase 3) blocks the
     third attempt.
  6. The conversation is deleted → check the offload cleanup (Phase 4, or
     check that the periodic job is scheduled if the cautious
     alternative was chosen).

---



## Recommended rollout sequence


| Step | Phase                            | Risk                          | Activation flag                                                                            |
| ---- | -------------------------------- | ----------------------------- | ------------------------------------------------------------------------------------------ |
| 1    | Phase 0 (bug fixes)              | Very low                      | None, direct fix                                                                           |
| 2    | Phase 1 (soft-delete)            | Medium (touches many queries) | No new flag: the observable behaviour stays identical, only persistence changes            |
| 3    | Phase 2 (ledger in mid-turn)     | Low                           | Inherits `AION_TOOL_LEDGER_ENABLED`/`AION_TOOL_OFFLOAD_ENABLED` (default on)               |
| 4    | Phase 3 (native circuit breaker) | Low                           | New flag `AION_TOOL_CIRCUIT_BREAKER_ENABLED` (default off until validated)                 |
| 5    | Phase 4 (offload cleanup)        | Low                           | No flag — but decide immediate/deferred (see question below)                               |
| 6    | Phase 5 (registry lock)          | Medium (concurrency)          | No flag, but deploy to staging with concurrent load before production                      |
| 7    | Phase 6 (observability)          | None                          | N/A                                                                                        |
| 8    | Phase 7 (integration tests)      | N/A                           | CI gate before enabling the flags above in production                                      |


Only after Phases 0-4 are in production and stable, evaluate whether to raise the
defaults of `AION_TOOL_OFFLOAD_ENABLED`/`AION_TOOL_LEDGER_ENABLED` from `0` to `1`
— today the plan leaves them opt-in.

---



## Phase 8 — Full history in chat-ui (implemented)

The chat-ui shows the **whole** history (messages with `archived_at` included).
The LLM context stays compacted via `history_manager.get_window()` / STM, which
excludes archived messages.

- **chat-ui API**: `GET /chat-ui/conversations/{id}/messages` — default
  `include_archived=true`; each archived row exposes `archived: true` (and
  optionally `archived_reason`).
- **Client**: `fetchConversationHistory()` always sends `include_archived=1`.
- **UI**: discreet label on archived messages; message editing
  disabled on archived rows.

The REST API `/v1/conversations/{id}/messages` keeps `include_archived=false`
by default for programmatic clients.

---



## Open questions before starting the implementation

1. **Phase 4**: do you prefer immediate deletion of the offloaded files when the
   conversation is deleted, or a deferred periodic job (safer if in the
   future you want a "restore conversation")?
2. **Phase 1**: do you want archived messages to stay in the table **forever**
   (only excluded from active queries), or is a retention
   policy/hard-delete after N days needed anyway for DB size or compliance reasons?
3. **Phase 3**: do you agree with moving `tool_circuit.py` from
   `pi_runtime/` to `src/runtime/` (shared module), or do you prefer two
   separate implementations to keep the two paths isolated even
   at the cost of minimal duplication?
4. Do you want me to proceed with implementing **Phase 0** (the two minimal-risk fixes)
   right away, or do you prefer to review the whole plan first?

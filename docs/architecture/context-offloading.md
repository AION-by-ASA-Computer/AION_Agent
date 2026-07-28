---
title: Context offloading — implementation plan
sidebar_position: 14
description: Three-layer plan (tool result offload, tool ledger, custom compaction) to keep agent context small without losing recoverable detail.
---

# Context offloading — implementation plan

Status: **implemented** (feature-flagged; enable via `.env`).

## Problem statement

Long turns (research + deliverable) lose information irreversibly. In the
"World Cup 2026 Excel" session the agent issued 24 `web_fetch_page` calls; each
result was capped and the excess **discarded**, then the surviving text was
compacted away. The agent ended the turn with neither the data nor a record of
having fetched it.

Two distinct failures:

1. **Write-time truncation.** `truncate_tool_result()` keeps head+tail and drops
   the middle forever. The decision to discard is made when the tool returns,
   not when the agent decides it does not need the content.
2. **No durable trace.** The DB holds a 223 KB `timeline_json` for that turn,
   but nothing from it re-enters the LLM context. After compaction the agent
   cannot answer "what have I already fetched?".

## Goals

- Move the retain/discard decision from **write-time to read-time**: full tool
  payloads live on disk, the agent pulls only the slice it needs.
- Give the agent a persistent, cheap **trace of tool calls** that survives
  compaction.
- Make compaction **tool-aware**: the summary must carry the ledger and the
  offload pointers, not only prose.
- Apply to **both** runtimes (Pi/`long_run` and Haystack), behind flags.

## Non-goals

- No new agent-facing tools. The existing sandbox tools are sufficient (see
  [L1 §Retrieval](#retrieval-no-new-tools)).
- No change to the SSE contract or to chat-ui rendering.
- No vector store / semantic retrieval over offloaded results (possible later).

## What Pi already provides

Verified against `@earendil-works/pi-coding-agent@0.82` in
`services/pi-long-run/node_modules/`.

| Capability | Where | Reusable? |
|---|---|---|
| Temp-file offload with `fullOutputPath` | `dist/core/tools/output-accumulator.js`, `BashToolDetails` | Pattern only — wired to the `bash` tool, which we disable (`noTools: "builtin"`) |
| `truncateHead` / `truncateTail` / `truncateLine`, `DEFAULT_MAX_BYTES` (50 KB), `DEFAULT_MAX_LINES` (2000) | exported from package root | Yes, for the worker-side extensions |
| Structured compaction + cumulative `readFiles`/`modifiedFiles` in `CompactionEntry.details` | `docs/compaction.md` | Yes — we extend `details` with our own keys |
| `serializeConversation(convertToLlm(msgs))` producing `[Assistant tool calls]: …` / `[Tool result]: …` (tool results cut at 2000 chars) | exported | Yes, for L3 |
| `generateSummary`, `calculateContextTokens`, `shouldCompact`, `getLatestCompactionEntry` | exported | Yes |
| Hook `tool_result` (middleware, can replace `content`/`details`) | `docs/extensions.md` §tool_result | Yes |
| Hook `context` (fires before each LLM call, `event.messages` is a modifiable deep copy) | `docs/extensions.md` §context | Yes, for L2 injection and L3b pruning |
| Hook `session_before_compact` (custom summary + arbitrary `details`) | `docs/extensions.md` §session_before_compact | Yes, for L3 |
| `ctx.getContextUsage()`, `ctx.compact({ customInstructions, onComplete, onError })` | `docs/extensions.md` §ExtensionContext | Yes |

**Gap:** Pi has no generic offloader for custom/bridged tools. Its own docs
state the requirement and leave it to the tool author
(`docs/extensions.md` §"Output Truncation": *"Tools MUST truncate their output …
Always inform the LLM when output is truncated and where to find the full
version"*). Our `aion-bridge.ts` does neither.

## Current AION behaviour — the loss points

| # | Location | Today | Consequence |
|---|---|---|---|
| 1 | `src/api/internal/pi_tools.py:51` | `truncate_tool_result(content, tool_name=…)` | Middle of payload lost; only `{content, is_error, truncated}` returned |
| 2 | `src/runtime/turn_compaction.py:217-235` | head `cap//2` + note + tail `cap//4` | Same loss on the Haystack path via `maybe_compact_after_tool` (line 1057) |
| 3 | `services/pi-long-run/extensions/aion-bridge.ts:93-96` | returns `{content, isError}` only | No `details` ⇒ no pointer in Pi's session JSONL |
| 4 | `services/pi-long-run/src/session-factory.ts:56-60` | single extension factory (`bridge`) | Extension array must grow for L2/L3 |
| 5 | `src/runtime/long_run_mode.py:39-55` | system prompt says "do not repeat full fetch dumps" | No mention of offloaded results or how to re-read them |

## Target architecture

```
tool returns 48 KB
        │
        ▼
  ┌─────────────────────────────────────────────┐
  │ L1  offload_tool_result()                   │
  │   full  → derived/tool_results/0007_….txt   │
  │   ctx   ← preview + pointer + how-to-read   │
  └─────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
  ┌──────────────────┐        ┌─────────────────────────┐
  │ L2  tool ledger  │        │ agent re-reads on demand │
  │  _ledger.jsonl   │        │  sandbox_read_file_chunk │
  │  → injected each │        │  sandbox_grep_content    │
  │    turn (~2 KB)  │        └─────────────────────────┘
  └──────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────┐
  │ L3  session_before_compact                  │
  │   summary + details{ledger, offloadPaths,   │
  │                     readFiles, modified}    │
  └─────────────────────────────────────────────┘
```

Ordering matters: offload first, ledger second, compaction last — mirroring the
hierarchy used by LangChain Deep Agents (offload results → offload stale inputs
→ summarize only when nothing is left to offload).

---

## L1 — Tool result offload

### New module: `src/runtime/tool_offload.py`

```python
@dataclass(frozen=True)
class OffloadedResult:
    text: str            # exactly what enters the LLM context
    path: str | None     # session-relative, e.g. "derived/tool_results/0007_web_fetch_page.txt"
    total_chars: int
    preview_chars: int
    offloaded: bool      # False ⇒ caller should fall back to truncate_tool_result

def offload_tool_result(
    result: str,
    *,
    session_id: str,
    tool_name: str,
    call_id: str | None = None,
    seq: int | None = None,
) -> OffloadedResult: ...
```

Behaviour:

1. If disabled, below threshold, tool is excluded, or `session_id` is invalid →
   return `OffloadedResult(text=result, offloaded=False, …)` and let the caller
   apply the existing `truncate_tool_result`. **Never raise into the tool path.**
2. Resolve `derived/tool_results/` via
   `src.session_workspace.safe_resolve(session_id, rel)`.
3. Write the full payload UTF-8. Filename
   `{seq:04d}_{slug(tool_name)}_{slug(call_id)}.txt`. Both slugs must match
   `_SAFE_REL = ^[a-zA-Z0-9._/\-]+$` (`src/session_workspace.py:19`) — sanitize,
   do not trust Pi call ids.
4. Build `text` = pointer header + preview.
5. Enforce the per-session byte budget, pruning oldest files first.

### Storage layout

`derived/` is already an allowed content root
(`SESSION_CONTENT_ROOTS`, `src/session_workspace.py:23`), so no change to
`session_workspace.py` is needed.

```
data/sessions/<sid>/derived/tool_results/
├── _ledger.jsonl                        # L2
├── 0001_web_search_call-a1.txt
├── 0007_web_fetch_page_call-b2.txt
└── 0012_sql_query_call-c3.json
```

Do **not** use a dot-prefixed directory: `sandbox_list_files` skips names
starting with `.`, which would make the store invisible to the agent.

### Pointer format

Keep it short, machine-scannable, and explicit about retrieval. Draft:

```
[AION offload] tool=web_fetch_page chars=48231 preview=1500
path=derived/tool_results/0007_web_fetch_page_call-b2.txt
Retrieve: sandbox_read_file_chunk(relative_path=<path>, offset_lines=0, max_lines=400)
Search:   sandbox_grep_content(pattern=<regex>, relative_root="derived")
--- preview (first 1500 chars) ---
<preview>
--- end preview ---
```

Tuning note from the field reports: the agent reasons over the **preview only**.
If the answer is buried and the preview does not hint at it, the agent misses
it. `AION_TOOL_OFFLOAD_PREVIEW_CHARS` is the knob to trade context against
recall; start at 1500 and measure.

### Retrieval — no new tools

The sandbox MCP server already exposes everything required:

| Tool | Signature | Role |
|---|---|---|
| `sandbox_read_file_chunk` | `(relative_path, offset_lines=0, max_lines=500, max_bytes=0)` | Claude-Code-style slice reader — **primary** retrieval path |
| `sandbox_grep_content` | `(pattern, relative_root="workspace", fixed_string=False, glob_filter="*", max_matches=200, …)` | Find the relevant span without loading the file |
| `sandbox_read_text_file` | `(relative_path, max_bytes=0)` | Whole-file read up to `AION_SANDBOX_READ_TEXT_MAX_BYTES` (default 2MB); omit `max_bytes` |

Callers must pass `relative_root="derived"` to grep the store; the default is
`workspace`. Document this in the pointer text.

Deployment benefit: retrieval executes **inside the Python backend**, so the Pi
worker container never needs access to the `aion_data` volume.

### Integration points

**(a) Pi path — `src/api/internal/pi_tools.py`**

Replace the `truncate_tool_result` call in `invoke_pi_tool`:

```python
off = offload_tool_result(
    content,
    session_id=body.session_id,
    tool_name=body.tool_name,
    call_id=body.call_id,
)
payload_text = off.text if off.offloaded else truncate_tool_result(
    content, tool_name=body.tool_name
)
return {
    "content": payload_text,
    "is_error": is_error,
    "truncated": (not off.offloaded) and payload_text != content,
    "details": {
        "offload_path": off.path,
        "total_chars": off.total_chars,
        "preview_chars": off.preview_chars,
    } if off.offloaded else None,
}
```

`body.call_id` already exists on `PiToolInvokeBody` but is currently unused —
the bridge must start sending it (see (c)).

**(b) Haystack path — `src/runtime/turn_compaction.py`**

`maybe_compact_after_tool(tool_name, result)` (line 1055) is the single
choke point. Resolve the session id from `resolve_turn_runtime()`, call
`offload_tool_result`, and keep the existing token-accounting and mid-turn
compaction logic untouched. `truncate_tool_result` stays as the fallback and
keeps its current tests green.

**(c) Bridge — `services/pi-long-run/extensions/aion-bridge.ts`**

- Pass `call_id: _toolCallId` in the POST body (currently dropped).
- Widen the response type with `details?: Record<string, unknown>` and return it
  from `execute`, so the pointer is persisted in Pi's session JSONL
  (`ToolResultMessage.details`) and becomes available to the `context` and
  `session_before_compact` hooks.

**(d) System prompt — `src/runtime/long_run_mode.py`**

Extend `build_long_run_system_prompt()` with a short section: large results are
offloaded, pointers look like `[AION offload]`, re-read with
`sandbox_read_file_chunk` / `sandbox_grep_content`, and never re-fetch a URL
that already has a pointer in the ledger.

### Exclusions — do not break chat-ui

`chat-ui` parses `web_search` step output to build source cards
(`webSearchSourceRows` in `chat-ui/lib/sse/webToolParse.ts`, consumed by
`historyMessageFromApi` in `ChatWorkspace.tsx`). Replacing that payload with a
pointer would silently kill the source-card UI.

**Decision:** `web_search` is excluded from offload by default. Its existing
structure-preserving compaction (`_truncate_web_tool_json`, TOON) is already
compact and must remain the value that reaches SSE and the DB.
`AION_TOOL_OFFLOAD_EXCLUDE` defaults to `web_search`.

Before enabling offload for any tool whose output the UI parses, confirm which
string is persisted as the step output and split the LLM-facing string from the
UI-facing one.

### Guardrails

- Total store cap `AION_TOOL_OFFLOAD_MAX_TOTAL_MB` (default 64), prune oldest.
- Cleanup on session deletion — hook into the existing session-cleanup path.
- Any exception inside offload is logged at `debug` and degrades to truncation.
- Never write outside `safe_resolve`; add a unit test asserting that a crafted
  `tool_name`/`call_id` containing `..` or `/` cannot escape.

---

## L2 — Tool ledger (the trace)

### New module: `src/runtime/tool_ledger.py`

Append-only JSONL at `derived/tool_results/_ledger.jsonl`, one line per call:

```json
{"seq":7,"ts":1753600000,"tool":"web_fetch_page","target":"…/2026_FIFA_World_Cup_Group_A","ok":true,"chars":48231,"path":"derived/tool_results/0007_web_fetch_page_call-b2.txt","dur_ms":2140}
```

- `target`: first meaningful string argument, trimmed to 60 chars. **Never the
  full argument object** — that is what blew up context in the first place.
- `path`: `null` when the result was small enough to stay inline.

```python
def append_ledger_entry(session_id: str, entry: LedgerEntry) -> None: ...
def render_ledger_table(
    session_id: str, *, max_rows: int = 60, max_chars: int = 3000
) -> str: ...
```

Rendered form (~20–30 tokens/row, so 100 calls ≈ 2–3 k tokens):

```
--- Tool trace (this session) ---
| #  | tool            | target        | ok | chars | full result |
| 3  | web_fetch_page  | Group_A       | y  | 10.3k | derived/tool_results/0003_web_fetch_page_call-a9.txt |
| 4  | web_fetch_page  | Group_B       | y  |  9.8k | derived/tool_results/0004_web_fetch_page_call-b1.txt |
… 38 earlier calls omitted (grep derived/tool_results/_ledger.jsonl)
--- End tool trace ---
```

Rows beyond `max_rows` collapse into the "omitted" line. The table is
**regenerated every turn** rather than stored in history, which is why it
survives compaction at constant cost.

### Injection

**v1 (Python only, no worker change).** Extend
`_resolve_pi_prompt_message` / `format_pi_history_prefix` in
`src/runtime/pi_runtime/pi_turn_runner.py` to prepend the ledger table on
**every** turn — not only when `session_created` is true, which is the current
condition for the history prefix. This reuses the hydration path landed for the
history fix.

**v2 (worker extension, better freshness).** New
`services/pi-long-run/extensions/aion-ledger.ts` on the `context` hook, fetching
`GET /internal/pi/ledger?session_id=…`. This refreshes the table *between tool
calls within the same turn*, which v1 cannot do. Ship v1 first, measure whether
mid-turn freshness matters.

**Haystack path.** Inject as a system message through the existing harness-v2
injection mechanism (`AION_HARNESS_V2_INJECTIONS`).

Note while editing `pi_turn_runner.py`: `List` is used in annotations at lines
26 and 36 but is not imported from `typing`. It is currently harmless because of
`from __future__ import annotations`; add the import.

---

## L3 — Tool-aware compaction

### New extension: `services/pi-long-run/extensions/aion-compaction.ts`

```typescript
pi.on("session_before_compact", async (event, ctx) => {
  const { preparation, customInstructions, reason, signal } = event;
  const transcript = serializeConversation(
    convertToLlm(preparation.messagesToSummarize),
  );
  // POST transcript + previousSummary + fileOps to AION, with ctx.signal
  // On any failure: return undefined  → Pi falls back to its own compaction.
  return {
    compaction: {
      summary,
      firstKeptEntryId: preparation.firstKeptEntryId,
      tokensBefore: preparation.tokensBefore,
      usage,
      details: { readFiles, modifiedFiles, toolLedger, offloadPaths },
    },
  };
});
```

Rules:

- **Never** return `{ cancel: true }` — that would let the context overflow.
- Timeout `AION_PI_COMPACTION_HTTP_TIMEOUT` (default 120 s); on timeout return
  `undefined` and log a warning.
- Always forward `ctx.signal` so Esc/abort cancels the summarization LLM call.
- Handle `reason === "overflow"` and `willRetry` — the aborted turn is retried
  after compaction, so the summary must be usable immediately.

### New endpoint: `POST /internal/pi/compaction/summarize`

Add to `src/api/internal/pi_tools.py` (same `X-Aion-Pi-Secret` check).
Body: `session_id`, `transcript`, `previous_summary`, `file_ops`,
`custom_instructions`. Reuse the existing summarization LLM in
`src/memory/context_compressor.py` rather than adding a second code path.

### Extended summary template

Pi's format plus two blocks, so the post-compaction agent knows *what it did*
and *where the data is*:

```markdown
## Goal … ## Progress … ## Next Steps … ## Critical Context …

<read-files>…</read-files>
<modified-files>…</modified-files>

<tool-trace>
3  web_fetch_page  Group_A  ok  10.3k  derived/tool_results/0003_….txt
</tool-trace>

<offloaded-results>
derived/tool_results/0003_web_fetch_page_call-a9.txt  (Group A fixtures, 10.3k)
</offloaded-results>
```

Because Pi accumulates `details` across successive compactions (documented for
`readFiles`/`modifiedFiles`), `toolLedger` and `offloadPaths` must be merged
with `preparation.previousSummary`'s `details`, not overwritten.

### L3b (optional) — prune stale tool inputs

`sandbox_write_workspace_file` calls leave the full file content in history even
though the content is already on disk. Above ~85 % context, a `context` hook can
replace those arguments with a path pointer. Deep Agents reports this as a
material saving. Ship only after L1–L3 are stable.

---

## Environment variables

Add to `.env.example` under the compaction block, all defaults chosen so that
**nothing changes until explicitly enabled**.

| Variable | Default | Purpose |
|---|---|---|
| `AION_TOOL_OFFLOAD_ENABLED` | `0` | Master gate for L1 |
| `AION_TOOL_OFFLOAD_MIN_CHARS` | `8000` | Offload threshold |
| `AION_TOOL_OFFLOAD_PREVIEW_CHARS` | `1500` | Preview kept in context |
| `AION_TOOL_OFFLOAD_EXCLUDE` | `web_search` | Comma-separated tool denylist |
| `AION_TOOL_OFFLOAD_MAX_TOTAL_MB` | `64` | Per-session store cap |
| `AION_TOOL_LEDGER_ENABLED` | `0` | Master gate for L2 |
| `AION_TOOL_LEDGER_MAX_ROWS` | `60` | Rows rendered before collapsing |
| `AION_TOOL_LEDGER_MAX_CHARS` | `3000` | Hard cap on injected table |
| `AION_PI_CUSTOM_COMPACTION` | `0` | Master gate for L3 |
| `AION_PI_COMPACTION_HTTP_TIMEOUT` | `120` | Worker → backend summarize timeout |

Reference thresholds from comparable systems, for calibration: Deep Agents
offloads above 20 k tokens with a 10-line preview; Strands `ContextOffloader`
defaults to 2 500 tokens; Haystack's `OffloadOverChars` + 200-char preview.
Our 8 000 chars (≈2 k tokens) is deliberately aggressive because our tool
results are dominated by web page extracts.

## Work breakdown

| # | Task | Files | Est. |
|---|---|---|---|
| 1 | `tool_offload.py` + unit tests | new module, `src/test/test_tool_offload.py` | 1 d |
| 2 | Wire Pi path | `src/api/internal/pi_tools.py`, `src/test/test_pi_tools_api.py` | 0.5 d |
| 3 | Wire Haystack path | `src/runtime/turn_compaction.py` | 0.5 d |
| 4 | Bridge `call_id` + `details` | `services/pi-long-run/extensions/aion-bridge.ts` + vitest | 0.5 d |
| 5 | System prompt guidance | `src/runtime/long_run_mode.py` | 0.25 d |
| 6 | `tool_ledger.py` + tests | new module, `src/test/test_tool_ledger.py` | 1 d |
| 7 | Ledger injection v1 | `src/runtime/pi_runtime/pi_turn_runner.py` | 0.5 d |
| 8 | Ledger injection Haystack | harness-v2 injections | 0.5 d |
| 9 | `/internal/pi/compaction/summarize` | `src/api/internal/pi_tools.py`, `src/memory/context_compressor.py` | 1 d |
| 10 | `aion-compaction.ts` + vitest | new extension, `session-factory.ts` | 1 d |
| 11 | Ledger `context` hook (v2) | `aion-ledger.ts` + `/internal/pi/ledger` | 0.5 d |
| 12 | Docs + `.env.example` | this file, `.env.example`, `long-run-pi-mode.md` | 0.5 d |

≈ 8 developer-days. Tasks 1–5 (L1) are independently shippable and already fix
the World Cup scenario.

## Testing

Python (`python -m pytest src/test/ -v`):

- `test_tool_offload.py` — below/above threshold; exclusion list; path traversal
  attempt via `tool_name`/`call_id`; invalid `session_id` falls back to
  truncation; store cap prunes oldest; preview is a byte-exact prefix.
- `test_tool_ledger.py` — append/render round-trip; `max_rows` collapse;
  `max_chars` cap; `target` never leaks full args.
- `test_pi_tools_api.py` — `details` present when offloaded, absent otherwise.
- **Regression, must stay green:** `test_toon_web_search_truncation.py`,
  `test_turn_compaction.py`, `test_context_recovery.py`.

TypeScript (`cd services/pi-long-run && pnpm test`):

- `aion-bridge.test.ts` — `call_id` sent, `details` forwarded.
- `aion-compaction.test.ts` — backend failure/timeout returns `undefined`;
  `cancel` is never returned; `details` merges the previous summary's.

Manual end-to-end: rerun the World Cup prompt in `long_run` with L1+L2 on.
Acceptance = 24 files under `derived/tool_results/`, a ledger table in context,
and the agent re-reading at least one offloaded file with
`sandbox_read_file_chunk` instead of re-fetching the URL.

## Acceptance criteria

1. With all flags off, behaviour is byte-identical to today.
2. With L1 on, no tool result is ever unrecoverable: every truncated payload has
   a readable file and a pointer.
3. With L2 on, after a compaction the agent can answer "which pages have you
   already fetched?" from context alone.
4. Injected ledger stays under `AION_TOOL_LEDGER_MAX_CHARS` regardless of call
   count.
5. chat-ui web source cards are unchanged (guarded by the `web_search`
   exclusion).
6. No path outside the session root is ever written.

## Rollout (gradual)

| Step | Flags | Environment |
|------|-------|-------------|
| 1 | `AION_TOOL_OFFLOAD_ENABLED=1` | dev/staging long_run |
| 2 | + `AION_TOOL_LEDGER_ENABLED=1` | dev/staging |
| 3 | + `AION_PI_CUSTOM_COMPACTION=1` | dev Pi worker |
| 4 | All three ON | production `long_run` |
| 5 | L1+L2 ON (Haystack normal) | production after long_run stable |

Restart `services/pi-long-run` after changing Pi-related flags so extensions reload.

## Risks

| Risk | Mitigation |
|---|---|
| chat-ui source cards break | `web_search` excluded by default; regression test |
| Agent ignores pointers and re-fetches | Explicit retrieval hint in pointer + system prompt section; measure re-fetch rate |
| Preview too small ⇒ agent misses buried answers | `AION_TOOL_OFFLOAD_PREVIEW_CHARS` tunable; start 1500 and calibrate per tool |
| Disk growth on long sessions | Per-session cap + oldest-first prune + cleanup on session delete |
| Custom compaction fails mid-overflow | Always fall back to Pi's default; never `cancel` |
| Offload adds latency in the tool path | Single synchronous file write; measure and move to a thread if it shows up |

## Open questions

1. Which string is persisted as the DB step output on the Pi path — the
   pre- or post-truncation value? Determines whether any UI-parsed tool other
   than `web_search` needs the exclusion.
2. Should offloaded files be exposed in the chat-ui artifacts panel? They are
   intermediate, not deliverables — proposal: no, keep them out of
   `sandbox_list_files` default listings by keeping them under `derived/`.
3. Retention across sessions: is there value in a cross-session offload store
   for LTM, or is per-session sufficient? Proposal: per-session for v1.

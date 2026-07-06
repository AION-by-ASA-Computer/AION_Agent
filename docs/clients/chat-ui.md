---
sidebar_position: 2
title: Chat UI (Next.js)
description: Main Next.js chat client, stack aligned with admin-ui.
---

# Chat UI (`chat-ui/`)

**Next.js 16 + React 19 + Tailwind 4** application separate from [`admin-ui`](./admin-ui.md), on dev port **8003** (`npm run dev` in `chat-ui/`).

## Quick start

```bash
cd chat-ui
cp .env.local.example .env.local
# Set NEXT_PUBLIC_AION_API_URL (e.g. http://localhost:8001)
npm install
npm run dev
```

Start the FastAPI API as usual (`uvicorn src.api.main:app`).

## Environment variables

**Local dev:** chat-ui first loads `.env` (and `.env.local`) from the **repo root** via `next.config.ts`, then any eventual `chat-ui/.env.local` as an override. There is no need to duplicate everything in `chat-ui/` — the root `.env` with the `NEXT_PUBLIC_*` is sufficient.

| Variable | Role |
|-----------|--------|
| `NEXT_PUBLIC_AION_API_URL` | FastAPI base URL (browser) |
| `NEXT_PUBLIC_AION_ADMIN_UI_URL` | admin-ui base for Agent DB iframe |
| `NEXT_PUBLIC_AION_CHAT_UI_SECRET` | Optional: same value as `AION_CHAT_UI_INTERNAL_SECRET` on the backend |
| _(removed)_ | Orchestration approve uses the **chat JWT** (`Authorization: Bearer`); do not expose orchestration secrets in the browser bundle |
| `NEXT_PUBLIC_AION_CHAT_UI_DEBUG` | **[hardcoded in `dev-flags.ts:7`]** — console log stream chunk counters (token / reasoning) |
| `NEXT_PUBLIC_AION_PROMPT_DEBUG` | **[hardcoded in `dev-flags.ts:8`]** — Prompt dock tab (requires `AION_PROMPT_DEBUG=1` on the backend) |
| `AION_AGENT_DB_EMBED_SECRET` | Next server only: route `/api/agent-db-embed` |

### Brand (logo / favicon)

Place assets in `chat-ui/public/`:

- `logo.svg` (preferred) or `logo.png` — shown in the header (`chat-ui/components/brand/ChatBrand.tsx`).
- `favicon.ico` — referenced by `chat-ui/app/layout.tsx` (`metadata.icons`).
- Optional: `apple-touch-icon.png` (180×180) for iOS.

If the files are missing, the UI uses the textual fallback **AION** without build errors.

Backend (`.env`): `AION_CORS_ORIGINS` can list `http://localhost:8003`; default `*` already allows all origins.

## Backend endpoints used

- `POST /chat` — SSE streaming
- `POST /sessions/{id}/upload`, `GET .../files`, `GET .../download`
- `GET /sessions/{id}/charts`
- `GET /sessions/{id}/events/stream` — session Redis events (plan approval)
- `POST /chat/stop` — stream interruption
- `GET /profiles`
- `POST /auth/login`, `GET /auth/me` — password login (requires `AION_CHAT_PASSWORD_AUTH=1`, legacy: `AION_CHAINLIT_PASSWORD_AUTH`)
- `GET|POST /chat-ui/conversations` — list/create conversations on the unified DB
- `GET /chat-ui/conversations/{id}/stream-status` — `/chat` turn still executing (reconnection after navigation)
- `POST /v1/chat/stream` — extended with `user_message_id`, `assistant_message_id`, `message_source` (API key)
- `GET /v1/integrations/status`, `GET /v1/integrations`, `POST /v1/integrations/credentials` — state and MCP credentials per user (Bearer chat; see [MCP Integrations (API)](../api-and-runtime/mcp-integrations-api.md))

## My integrations

Path: `/integrations`. Panel for personal credentials on servers with `credential_mode=per_user` (`AION_MCP_USER_CREDENTIALS=1`). With `org_shared` a message appears stating that the integration is managed by the administrator (no form). Link from the chat sidebar.

## Feature checklist

| Feature | Status |
|---------|--------|
| Stream token / reasoning / error | Yes (`lib/sse/`) |
| Interleaved timeline (reasoning → tool → text in SSE order) | Yes (`TurnTimeline`, `segments` in `reducer.ts`) |
| Tool steps tool_event (id `tc_*`, running + parameters in full view) | Yes |
| Artifact start/content/end | Yes — from sandbox write/edit/patch `tool_start` (file preview bridge), not only legacy stream XML |
| File generation shimmer (`StatusProgressCard`) | Yes — on `tool_start` for `sandbox_write_*` / `edit` / `apply_patch` when preview payload present (`lib/sse/filePreviewTools.ts`, `reducer.ts`) |
| `orchestration_plan_pending` + Plan dock | Yes (`TaskPlanManagerV4.jsx`) |
| `presentation_preview` | Yes |
| `/db` → Agent DB iframe | Partial (component + BFF exist but trigger commented out in ChatWorkspace) |
| Upload + merge session attachments | Yes |
| Post-turn charts | Yes (Recharts, data from `/sessions/.../charts`) |
| New session files (uploads/workspace/derived) | Yes |
| Profile + reasoning effort | Yes |
| Plan approval listener → `internal_trigger` | Yes (SSE session events) |
| Login DB users | Yes (`/auth/login`) |
| Thread list `/chat-ui/conversations` | Yes |
| Stream recovery after exit/re-entry of chat | Yes (Redis `stream_active` + history poll every 2s) |
| Plan recovery on network error / artifact fallback | Partial (not duplicated client-side) |
| CoT messages auto-collapse | Partial |

## Tool and thinking visualization

- **`localStorage` `aion_chat_tools_view`**: `hidden` | `partial` | `full` (recommended default: `full` for debug).
- In **`full`**, each step shows **Parameters** (JSON input at `tool_start`) and **Response** (output at `tool_end`).
- During MCP execution the card remains visible with **Running** badge and spinner (not just at tool end).
- The reducer keeps `segments[]` in SSE arrival order; no longer the fixed layout reasoning-at-the-top / tool-below.

### File preview and artifact dock (tool-first)

When the agent calls `sandbox_write_workspace_file`, `sandbox_edit_workspace_file`, or `sandbox_apply_patch`, the backend may emit early `artifact_*` SSE events bridged from `tool_start` (see [Agent pipeline](../api-and-runtime/agent-pipeline.md#tool-first-file-delivery-opencode-style)). The chat-ui:

- Recognizes file-preview tools via `chat-ui/lib/sse/filePreviewTools.ts`.
- Shows **StatusProgressCard** (“Generating document…”) when `hasPreviewPayload` is set on the tool step.
- Opens **StreamingContentPreview** in the dock with streamed file body when available.
- Uses `generatingTitleForFileTool()` for the filename label (from `relative_path` in tool args).

During long reasoning **before** `tool_start`, only the reasoning block is visible (no shimmer until the tool call is parsed and emitted).

## Persisted timeline (history / saving)

- **DB**: additive column `messages.timeline_json` (JSON array of segments: `reasoning` | `tool` | `artifact` | `text`).
- **API** (`GET /chat-ui/conversations/{id}/messages`): **[the `timeline` field is currently not exposed by the GET API]** — existing fields (`content`, `reasoning`, `tool_name`, `tool_call_id`, `created_at`) remain unchanged for legacy integrations.
- **New turns**: `agent_pipeline` builds the timeline from the same SSE chunks sent to the client.
- **Historical messages**: automatic backfill on `./scripts/upgrade-aion.sh`, `scripts/init_unified_db.py`, setup wizard and backend startup (idempotente); manual: `python scripts/backfill_message_timelines.py`. Best-effort: reasoning at the head, tool/artifact by `created_at`, text at the tail. GET also does lazy-backfill if `timeline_json` is still null.
- **Chat-ui**: `segmentsForMessage()` prefers `timeline` / `segments` in memory; fallback `segmentsFromHistoryMessage()` only if absent.

## Design system

The chat-ui uses CSS tokens from `chat-ui/styles/theme-tokens.css`: **HSL variables without `hsl()` wrapper** (shadcn pattern: `hsl(var(--primary))`), radius `--radius: 0.875rem`, primary **red/coral** (`hue 0`), sidebar and chart palettes aligned.

| CSS Token | Use in UI |
|-----------|-----------|
| `--background` / `--foreground` | Main shell and text |
| `--card` / `--card-foreground` | Assistant bubble, content card |
| `--primary` / `--primary-foreground` | User bubble, CTA (Send), link accents |
| `--muted` / `--muted-foreground` | Reasoning disclosure, secondary toolbar, caption |
| `--border` / `--input` / `--ring` | Input borders, composer, focus ring (`focus-ring` in `globals.css`) |
| `--secondary` | Dock column (light secondary background) |
| `--destructive` | Stop stream, login error messages |
| `--sidebar-*` | Thread sidebar (background, active item, border) |
| `--chart-1` … `--chart-5` | Series in Recharts charts (`SessionCharts`) |

Technical implementation:

- **`chat-ui/styles/theme-tokens.css`** — dark/light values from `theme.json`; theme with `data-theme="dark|light"` on `<html>`.
- **`chat-ui/app/globals.css`** — `@import` of the theme, `@theme inline` Tailwind v4 for semantic utilities (`bg-background`, `text-primary`, …), **`.prose-chat`** class for markdown without `@tailwindcss/typography`.
- **`next/font/google` Inter** — `--font-sans` variable on `<html>` (`app/layout.tsx`).
- **`AppShell`** — sidebar + main + dock grid; **resizable** dock width (handle between chat and dock, `localStorage` persistence with key `aion-chat-dock-w`).
- **Theme toggle** — sun/moon button in the header (`ThemeToggle`); `localStorage` persistence with key `aion-chat-theme`; `beforeInteractive` script avoids initial flash.
- **TaskPlanManagerV4** (`dock/`) — inline styles referencing `--primary`, `--muted`, `--popover`, `--radius`, etc.: all defined in the global theme above.

### Accessibility and polish

- Visible focus: `.focus-ring` utility (`ring-2` + `ring-offset-background`).
- Message area: `aria-busy` during streaming, `aria-live="polite"`.
- Layout shift reduction: streaming bubble with `min-h-[3.5rem]` and pulse indicators before assistant text.

### Visual QA Checklist

- [ ] Sidebar: text contrast on `--sidebar-background`, readable active state.
- [ ] User bubble: readability on `--primary` in dark and light.
- [ ] Composer: focus on textarea with `--ring`; Stop / Send buttons distinguishable.
- [ ] Dock: active tab with primary border; Presentation / Agent DB iframe with `rounded-aion` and `border-border`.
- [ ] Charts: readable axes/tooltips on light and dark theme.
- [ ] Light mode: no residue of a "generic blue" palette; accents remain on the theme's primary.

### Screenshots

Update this section with dark/light captures from the active chat-ui (header + sidebar + messages + dock) when available.

## Streaming and reasoning (troubleshooting)

- **Real-time tokens**: during the turn, the assistant response is rendered as **raw text** (no Markdown) to reduce load on the main thread; at the end of the turn, the message in the history uses Markdown as before.
- **Reasoning**: the UI shows chunks only if the backend sends SSE events with `type: "reasoning"` (depends on the model/generator and Thinking / `reasoning_effort`). With Thinking active and no chunks, an explanatory note appears below the saved message.
- **SSE**: the parser normalizes `\r\n` and maps error frames `{ "error": "..." }` (without `type`) to `error` chunks.
- **Debug**: with `NEXT_PUBLIC_AION_CHAT_UI_DEBUG=1`, after each turn the console shows `tokenChunks` and `reasoningChunks` to verify if the issue is model-side or network/UI-side.
- **Reconnection**: if you leave the chat while a turn is in progress, upon return the UI queries `GET /chat-ui/conversations/{id}/stream-status` (Redis key `aion:stream_active:{conversation_id}`) and updates the history every ~2s until the end; `chat.stream_recovery` banner and timeline rebuilt from the already persisted steps.

### Empty history upon return (sidebar)

- **Symptom**: you change chat from the sidebar and upon returning you do not see previous messages (without a full refresh).
- **Common causes**:
  - `GET /chat-ui/conversations/{id}/messages` in error (403 secret, 404 conversation/user, 503 unified DB disabled) — the UI shows the `chat.history_load_error` banner instead of a silent empty chat.
  - Stream still active on another conversation that was blocking the merge (mitigato: abort + `chatStop` on thread change, merge only for the conversation in stream) [Nota: "mitigato" was "mitigato" or "mitigato" -> let's double check, line 161 in original: "mitigato: abort + `chatStop` al cambio thread" wait, original line 161: "mitigato: abort + `chatStop` al cambio thread" in the view_file was actually "mitigato" or "mitigato" -> wait, line 161 says "(mitigato: abort..." wait, let's look at the view_file output:
  "  - Stream ancora attivo su un’altra conversazione che bloccava il merge (mitigato: abort + `chatStop` al cambio thread, merge solo per la conversazione in stream)."
  So "mitigato: abort + `chatStop` al cambio thread" translates to "mitigated: abort + `chatStop` on thread change"]
  - Messages in the DB but filtered as technical (role `internal`, orchestrator content, empty assistant without steps/timeline).
- **Debug**: `NEXT_PUBLIC_AION_CHAT_UI_DEBUG=1` logs in the console `[aion-chat-ui] history fetch` with `count`, `streamingRef`, `source`. Verify alignment of `AION_CHAT_UI_INTERNAL_SECRET` (backend) and `NEXT_PUBLIC_AION_CHAT_UI_SECRET` (chat-ui).
- **Implementation**: local/server merge in `chat-ui/lib/merge-chat-history.ts`, orchestration in `chat-ui/lib/use-conversation-transcript.ts`.

### Streaming / reasoning QA checklist

- [ ] With API on `NEXT_PUBLIC_AION_API_URL`, tokens appear incrementally (raw text) during the turn.
- [ ] With a model that exposes CoT, the "Agent Analysis" panel populates during the turn.
- [ ] With Thinking OFF or effort `min`, no misleading messages about missing reasoning (only when Thinking is ON).
- [ ] Login and thread lists continue to point to the backend (absolute URL, not just Next origin).
- [ ] Start a long turn, change conversation or reload the page, return: recovery banner + tool steps advancing until the final message.

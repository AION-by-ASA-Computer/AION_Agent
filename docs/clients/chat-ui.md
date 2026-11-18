---
sidebar_position: 2
title: Chat UI
description: The web app where users chat with AION, plus how to configure and run it.
---

# Chat UI (`chat-ui/`)

Chat UI is the web application where people talk to AION: they pick an agent profile, ask questions, upload files and get answers, documents and charts back. It is the main client for end users. Administrators manage users, profiles and integrations in a separate app, the [Admin UI](./admin-ui.md).

Technically it is a **Next.js 16 + React 19 + Tailwind 4** application, separate from `admin-ui`, served on dev port **8003** (`npm run dev` in `chat-ui/`).

:::tip On this page
- **End users**: read [What you can do with Chat UI](#what-you-can-do-with-chat-ui), [User settings](#user-settings-settings) and [My integrations](#my-integrations).
- **Administrators / IT**: also read [Environment variables](#environment-variables) and [Brand (logo / favicon)](#brand-logo--favicon).
- **Developers**: everything from [Backend endpoints used](#backend-endpoints-used) onwards (timeline, design system, troubleshooting).
:::

## What you can do with Chat UI

- **Chat with an agent**: choose a profile and a reasoning effort, then follow the answer as it streams, including the agent's reasoning and the tools it calls.
- **Work with files**: upload documents (legacy Word `.doc` files are converted automatically), and preview or download the files the agent creates in the side dock.
- **See charts inline**: charts produced by the agent appear directly in the conversation and are restored when you reload.
- **Dig into a passage**: select text in an answer and open a [side thread](./side-threads.md) without cluttering the main chat.
- **Dictate**: use the microphone button to speak instead of typing (when enabled by the administrator).
- **Approve plans**: when the agent proposes a multi-step plan, review and approve it from the Plan dock.
- **Tune the agent**: adjust limits and generation parameters from the sidebar and save them as presets.
- **Manage your account**: profile, appearance, password, personal API keys, personal instructions and credentials for your own integrations.
- **Pick up where you left off**: conversations are saved; if you leave during a long answer, the chat resumes when you come back.

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
| _(removed)_ `NEXT_PUBLIC_AION_CHAT_UI_SECRET` | Never expose `AION_CHAT_UI_INTERNAL_SECRET` in the browser bundle: chat-ui authenticates with the chat token (`Authorization: Bearer`) |
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
- Charts arrive inline: `chart` tool event on the `/chat` SSE stream, and `{kind: "chart"}` timeline segments in `GET /chat-ui/conversations/{id}/messages` (see [Session Charts](../api-and-runtime/session-charts.md))
- `GET /sessions/{id}/events/stream` — session Redis events (plan approval)
- `POST /chat/stop` — stream interruption
- `GET /profiles`
- `POST /auth/login`, `GET /auth/me` — password login (requires `AION_CHAT_PASSWORD_AUTH=1`)
- `GET|POST /chat-ui/conversations` — list/create conversations on the unified DB
- `GET|POST /chat-ui/conversations/{id}/threads` — side threads of a conversation ([Side threads](./side-threads.md))
- `GET /chat-ui/conversations/{id}/stream-status` — `/chat` turn still executing (reconnection after navigation)
- `POST /v1/chat/stream` — extended with `user_message_id`, `assistant_message_id`, `message_source` (API key)
- `GET /v1/integrations/status`, `GET /v1/integrations`, `POST /v1/integrations/credentials` — state and MCP credentials per user (Bearer chat; see [MCP Integrations (API)](../api-and-runtime/mcp-integrations-api.md))
- `GET|PUT /v1/runtime-settings` — allowlisted turn limits and generation kwargs (sidebar Tunings)
- `POST|PATCH|DELETE /v1/runtime-settings/presets` — per-user named snapshots (max 20)
- `GET|POST /v1/me/api-keys`, `DELETE /v1/me/api-keys/{id}` — personal API keys (Settings → API keys; see [API keys](../security/api-keys.md))
- `GET /v1/voice/status`, `POST /v1/voice/transcribe` — voice dictation (microphone button; see [Speech-to-text](../mcp/speech-to-text.md#dettatura-da-chat-ui))

## Sidebar tunings (runtime + presets)

**Tuning e parametri** ("Tuning and parameters", in the sidebar nav) opens a **sidebar panel** while the current chat stays in the main column. Deep-link: `/c/{id}?tunings=runtime` or `?tunings=presets`.

- **Runtime** tab: data-driven sliders from `GET /v1/runtime-settings` (loop limits, sampling, thinking). `.env` values are the Reset defaults; the server clamps every field.
- **Presets** tab: save / apply / rename / delete user-scoped snapshots stored in `users.metadata.runtime_settings`.
- Composer Thinking / effort stays a shortcut into the same store. Each `POST /v1/chat/stream` sends `runtime` so the turn is deterministic.

Hard ceilings (cannot be raised from the UI): 200 agent steps, 200 tool calls per turn. A profile YAML `max_agent_steps` can still cap lower.

## User settings (`/settings`)

Full-page route (profile menu → **Impostazioni**, i.e. "Settings"): profile, appearance, security, API keys, instructions (`USER.md`). Same layout as before the tunings panel — not embedded in the sidebar.

The **API keys** tab (`/settings?tab=api-keys`, shown only with a chat login token) lets the user create, list and revoke personal keys within the policy set by the admin (enabled flag, max active keys, max lifetime). The full key is shown only once at creation. Keys act as the user; see [API keys](../security/api-keys.md).

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
| Legacy `.doc` → `.docx` on upload (API host; fields `converted_docx_path`, `conversion_status`) | Yes — see [Office and legacy Word](../configuration/office-and-legacy-word.md) |
| Inline charts (live during streaming, restored on reload) | Yes (Recharts `ChartBlock`, see [Session Charts](../api-and-runtime/session-charts.md)) |
| New session files (uploads/workspace/derived) | Yes |
| Profile + reasoning effort | Yes |
| Sidebar tunings + presets | Yes (`SidebarTuningsPanel`, `GET/PUT /v1/runtime-settings`) |
| User settings page `/settings` | Yes (profile, appearance, security, instructions) |
| Plan approval listener → `internal_trigger` | Yes (SSE session events) |
| Login DB users | Yes (`/auth/login`) |
| Thread list `/chat-ui/conversations` | Yes |
| Stream recovery after exit/re-entry of chat | Yes (Redis `stream_active` + history poll every 2s) |
| Plan recovery on network error / artifact fallback | Partial (not duplicated client-side) |
| CoT messages auto-collapse | Partial |
| Side threads (select a passage → child conversation in the dock) | Yes — see [Side threads](./side-threads.md) |
| Voice dictation (microphone → text in the composer, Esc cancels) | Yes (`VoiceInputButton`, `hooks/use-voice-dictation.ts`); shown only when `/v1/voice/status` is enabled and the page is HTTPS or `localhost` |

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
- **API** (`GET /chat-ui/conversations/{id}/messages`): each assistant message includes `timeline` (the parsed segments), alongside `steps`, `artifacts`, `rating` and `feedback_comment`; existing fields (`content`, `reasoning`, `tool_name`, `tool_call_id`, `created_at`) remain unchanged for legacy integrations.
- **New turns**: `agent_pipeline` builds the timeline from the same SSE chunks sent to the client.
- **Historical messages**: automatic backfill on `./scripts/upgrade-aion.sh`, `scripts/init_unified_db.py`, setup wizard and backend startup (idempotent); manual: `python scripts/backfill_message_timelines.py`. Best-effort: reasoning at the head, tool/artifact by `created_at`, text at the tail. GET also does lazy-backfill if `timeline_json` is still null.
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
| `--chart-1` … `--chart-8` | Categorical series colors in inline charts (`SessionCharts.tsx`), fixed order, light/dark variants |

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
  - Stream still active on another conversation that was blocking the merge (mitigated: abort + `chatStop` on thread change, merge only for the conversation in stream).
  - Messages in the DB but filtered as technical (role `internal`, orchestrator content, empty assistant without steps/timeline).
- **Debug**: `NEXT_PUBLIC_AION_CHAT_UI_DEBUG=1` logs in the console `[aion-chat-ui] history fetch` with `count`, `streamingRef`, `source`. With password auth on, verify the chat token is present: `X-AION-User-Id` alone does not select the user.
- **Implementation**: local/server merge in `chat-ui/lib/merge-chat-history.ts`, orchestration in `chat-ui/lib/use-conversation-transcript.ts`.

### Streaming / reasoning QA checklist

- [ ] With API on `NEXT_PUBLIC_AION_API_URL`, tokens appear incrementally (raw text) during the turn.
- [ ] With a model that exposes CoT, the "Agent Analysis" panel populates during the turn.
- [ ] With Thinking OFF or effort `min`, no misleading messages about missing reasoning (only when Thinking is ON).
- [ ] Login and thread lists continue to point to the backend (absolute URL, not just Next origin).
- [ ] Start a long turn, change conversation or reload the page, return: recovery banner + tool steps advancing until the final message.

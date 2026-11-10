---
title: Deep Research
sidebar_position: 12
description: IterResearch-style deep web research with HTML reports and Deep Research Mode.
---

# Deep Research Integration

AION Agent includes a native **Deep Research** module, ported from the [Odysseus](https://github.com/) IterResearch loop under Apache 2.0 license (see [DeepResearch-Apache-2.0.txt](licenses/DeepResearch-Apache-2.0.txt)). 

Instead of generating quick, single-turn chat answers, this module executes an autonomous, multi-step research loop: **Plan $\rightarrow$ Search $\rightarrow$ Extract $\rightarrow$ Synthesize $\rightarrow$ Stop**. It streams progress in real time via Server-Sent Events (SSE) and persists results as self-contained HTML reports with advanced layout options.

---

## Architecture & Workflow

The deep research engine runs completely in the background via FastAPI's event loop or the main application global loop. The flow proceeds as follows:

```mermaid
graph TD
    A[User/Agent Query] --> B(Probing LLM & Search Providers)
    B --> C{Rounds Cap Reached?}
    C -- No --> D[Plan Strategy / Generate Search Queries]
    D --> E[Execute Web Search]
    E --> F[Scrape & Extract Page Content]
    F --> G[Analyze Findings & Synthesize Context]
    G --> C
    C -- Yes / Timeout / Stop --> H[Compile Final Markdown Report]
    H --> I[Generate Visual HTML Report]
    I --> J[Save to data/deep_research/session_id.json]
```

1. **Probing**: The engine verifies connection to the LLM model and checks active search providers (Tavily, Brave, or SearXNG). A failed probe (unreachable endpoint, rejected key, unknown model) ends the job with status `error` and the reason, instead of running every phase on empty LLM output.
2. **Planning**: An LLM agent plans a search strategy for the current round and translates the research goal into specific search queries.
3. **Searching**: Queries are executed using the configured search providers.
4. **Reading / Page Extraction**: The engine scrapes the retrieved URLs in parallel to extract text and findings, filtering out low-quality or irrelevant content.
5. **Analyzing & Synthesizing**: Collected findings are integrated into the running session state.
6. **Writing**: When the safety cap or time budget is reached, or the agent determines that it has gathered sufficient details, it compiles the final report, applies styling rules, and generates a visual HTML report page.

---

## Deep Research Mode

The AION system supports a dedicated **Deep Research Mode** (represented by a **violet** theme in the Chat UI), distinct from normal chat mode and the orange-themed **Plan Mode**.

Deep Research Mode is available on **every profile**: the chat-ui selector is always shown and the backend adds `trigger_research` / `manage_research` to the agent in this mode even when the profile has no Deep Research connector (see [Availability rules](#availability-rules)).

When the agent is placed in Deep Research Mode:
- **System Prompt Modifications**: The system prompt (rebuilt every turn by `refresh_agent_turn_context`) tells the model that its first and only action is `trigger_research` with the user's request as `topic`: no clarifying questions, no planning, no answer from its own knowledge (the research pipeline does all of that). After the tool returns it only replies with the progress anchor; on a tool error it reports the error.
- **Resident tools**: `trigger_research` / `manage_research` have their full schema on the first model call (never deferred behind `tool_search`), so the first step can be the tool call.
- **Tool Blocking**: To enforce the autonomous loop, standard tools that modify the environment, execute code, or perform basic single-step lookups are blocked. These include:
  - `web_search` and `web_fetch_page` (replaced by the autonomous loop)
  - Plan execution tools (`draft_execution_plan`, `get_execution_plan`, `update_execution_plan`, `mark_task_completed`)
  - Sandbox command execution and file editors (`sandbox_write_workspace_file`, `sandbox_edit_workspace_file`, `sandbox_exec_allowlisted`, etc.)
  - Subagent delegation (`delegate_to_subagent`)
  - Skill tools (`skill_view`, `skill_search`, `skill_list`), which otherwise distracted the model before starting the job

### Mode Comparison Matrix

| Feature | Normal Mode | Plan Mode | Deep Research Mode |
| :--- | :--- | :--- | :--- |
| **UI Color Theme** | Dark/Light Neutral | Orange | **Violet** |
| **Output Type** | Direct chat response | Interactive execution plan | **Autonomous visual HTML report** |
| **User Approvals** | Optional (standard rules) | Required for each task step | **Not required** (autonomous background execution) |
| **Primary Web Tool**| `web_search` (quick lookup) | `web_search` / `web_fetch_page` | **`trigger_research`** (IterResearch loop) |
| **Execution Context**| Synchronous turn | Human-in-the-loop task tracker | **Asynchronous background task** |

---

## Environment Configuration

Configure the deep research engine using the following keys in your `.env` file:

| Variable | Default Value | Bounds / Constraints | Purpose |
| :--- | :--- | :--- | :--- |
| `AION_DEEP_RESEARCH_ENABLED` | `1` | `0` or `1` | Master switch to enable/disable the module and register its native tools. |
| `AION_DEEP_RESEARCH_MAX_ROUNDS` | `8` | `1` to `32` | Safety cap on the maximum number of search/synthesize rounds. |
| `AION_DEEP_RESEARCH_MAX_TIME` | `600` | `60` to `3600` | Time budget in seconds for the entire research run. |
| `AION_DEEP_RESEARCH_RUN_TIMEOUT` | `1800` | `60` to `86400` | Absolute hard timeout in seconds on background task execution. |
| `AION_DEEP_RESEARCH_DATA_DIR` | `data/deep_research` | Absolute or relative path | Output directory for saving reports and status JSON files. |
| `AION_DEEP_RESEARCH_MAX_TOKENS` | `16384` | Integer | Token budget allocated to the LLM for report synthesis. |
| `AION_DEEP_RESEARCH_MAX_CONCURRENT`| `2` | Integer ($\ge 1$) | Maximum number of concurrent research runs allowed per user. |
| `AION_DEEP_RESEARCH_EXTRACTION_TIMEOUT` | `90` | `15` to `3600` | Hard timeout in seconds for downloading and parsing a single webpage. |
| `AION_DEEP_RESEARCH_EXTRACTION_CONCURRENCY` | `3` | `1` to `12` | Number of webpages extracted in parallel during a round. |
| `AION_DEEP_RESEARCH_BLOCKED_TOOLS` | *(Default list)* | Comma-separated strings | List of tool names to block when resolved agent mode is `deep_research`. |
| `AION_DEEP_RESEARCH_LLM_STREAM` | `1` | `0` or `1` | Stream the research LLM calls. Keeps long generations (the final report) alive through gateways that close silent requests after 60 s with HTTP 504. |
| `AION_DEEP_RESEARCH_THINKING_BUDGET` | `512` | Integer, `0` = off | `thinking_token_budget` sent to vLLM-style endpoints and **added** to each call's `max_tokens`, so reasoning models still write visible text (short calls such as the 20-token category check were otherwise eaten by reasoning). Dropped automatically if the endpoint answers 400. |
| `AION_DEEP_RESEARCH_REPORT_TIMEOUT` | `600` | Integer ≥ `60` | Total seconds allowed to write the final report (and its optional expansion). |
| `AION_DEEP_RESEARCH_LENGTH_RETRY_TOKENS` | `8192` | Integer, `0` = off | When an answer is empty with `finish_reason=length` (the model reasoned until `max_tokens`, typical on long page-extraction prompts where the router ignores the thinking budget), the call is retried once with this many extra tokens. |

---

## Agent Tools

When `AION_DEEP_RESEARCH_ENABLED=1`, the following two in-process tools are registered according to the [Availability rules](#availability-rules):

### 1. `trigger_research`

Starts a deep research background job on a target topic.

- **Parameters**:
  - `topic` (string, **required**): The research question, objective, or topic description.
  - `max_rounds` (integer, optional): Maximum search rounds (defaults to `AION_DEEP_RESEARCH_MAX_ROUNDS`).
  - `max_time` (integer, optional): Maximum execution seconds (defaults to `AION_DEEP_RESEARCH_MAX_TIME`).
  - `category` (string, optional): Research type constraint. Supported values: `product`, `comparison`, `howto`, `factcheck`.
- **Output**: Returns a JSON string payload containing a markdown anchor pointing to the session ID:
  ```json
  {
    "output": "Deep research started: [topic](#research-rp-abc123xyz). Open the Deep Research panel to watch progress and read the report.",
    "session_id": "rp-abc123xyz",
    "research_session_id": "rp-abc123xyz",
    "anchor": "[topic](#research-rp-abc123xyz)",
    "ui_event": "research_started",
    "query": "topic",
    "exit_code": 0
  }
  ```

### 2. `manage_research`

Lists, retrieves, or deletes saved research reports from the user's library.

- **Parameters**:
  - `action` (string, **required**): One of `list`, `read`, or `delete`.
  - `id` (string, optional): The target research session ID (required for `read` and `delete`).
  - `search` (string, optional): A text filter to query the report library by topic.
- **Output**: Returns a formatted text report/list or a status code (e.g., `Deleted research rp-abc123xyz.`).

---

## Profiles Registration

To expose deep research tools to a specific profile, list the `deep_research` bundle under the `native_tool_groups` section in the profile YAML (e.g., [aion_std.yaml](config_std/profiles/aion_std.yaml)), or toggle it in admin-ui → Profiles → Tools → Built-in:

```yaml
native_tool_groups:
  - web_research
  - deep_research
```

Profiles that still list `deep_research` under `mcp_servers` (legacy form; no
such MCP server exists, the job runs in-process) count as having the connector
too. That slug is never offered as a loadable MCP group by `tool_search`.

### Availability rules

Deep Research does **not** depend on the profile's other MCP servers or native
groups: it is a self-contained pipeline. The only check is the connector
(`src/runtime/deep_research_tools.py`, `deep_research_tools_allowed`):

| Profile has the connector | Chat mode | `trigger_research` callable |
| :--- | :--- | :--- |
| yes | normal / plan / ask / debug | yes |
| no | normal / plan / ask / debug | no |
| any | **Deep Research** | **yes** |

`AION_DEEP_RESEARCH_ENABLED=0` disables the tools everywhere. The resolved
agent mode is part of the agent cache key, so the Deep Research agent of a chat
session never leaks its tools into the normal-mode agent of the same session.

Once started, the job does not inherit anything from the calling profile: it
receives only the topic, the owner (for the library and UI language) and the
chat session id, and uses the platform web search providers and LLM directly.

---

## Time budget

Three limits keep a run bounded with slow reasoning models:

- **Per call** (`timeout` of each LLM call: page extraction =
  `AION_DEEP_RESEARCH_EXTRACTION_TIMEOUT`, analysis 300 s, report =
  `AION_DEEP_RESEARCH_REPORT_TIMEOUT`): a **total** deadline, retries
  included. With streaming the HTTP read timeout only bounds the gap between
  chunks, so the bridge enforces the total itself; a call past its deadline
  returns empty and the run goes on.
- **Per run** (`max_time`, the research budget): checked before each round
  and before each queued page. When it is reached, pages not started yet are
  skipped and the run moves on to analysis and the final report.
- **Hard stop** (`AION_DEEP_RESEARCH_RUN_TIMEOUT`, default 1800 s): last-resort
  cap on the whole job; on expiry the evolving report is saved. Raise it (up
  to 86400) only if runs legitimately need longer.

## Troubleshooting

- **Job ends at once with `LLM endpoint HTTP 4xx …`**: the LLM rejected the
  provider's key or model. The bridge uses the same URL, model and key as the
  chat agent (`resolve_llm_credentials`, see
  [LLM provider and API key precedence](../configuration/llm-provider-precedence.md)).
  With a key-scoped router ("Model … is not allowed for this API key") set the
  provider's model to one the key may use (e.g. `auto`) in admin-ui → LLM
  providers.
- **Report missing, only raw "Finding N" blocks saved** ("Final report output
  too brief … falling back to evolving report" in the logs): the
  report-writing LLM call returned nothing. Two known causes, both handled by
  the bridge now:
  - `504 Gateway Timeout` after exactly 60 s: the gateway closes requests that
    stay silent; the bridge streams (`AION_DEEP_RESEARCH_LLM_STREAM=1`).
  - `LLM returned empty content` with `finish=length`: a reasoning model spent
    the whole `max_tokens` thinking (the AION router ignores
    `chat_template_kwargs.enable_thinking`); the bridge caps it with
    `thinking_token_budget` (`AION_DEEP_RESEARCH_THINKING_BUDGET`) and adds the
    same amount to `max_tokens`, so even short calls have room to answer. On
    long prompts the router ignores the budget; an empty `finish=length`
    answer is then retried once with `AION_DEEP_RESEARCH_LENGTH_RETRY_TOKENS`
    more. The warning logs `finish`, `reasoning_chars`, `max_tokens` and
    `prompt_chars` to tell these cases apart.
- **Report in the wrong layout** (price table, "Prezzo indicativo" under each
  section on a topic that is not a purchase): the auto-detected category was
  `product`. The classifier describes when each category applies and falls
  back to the generic layout unless the reply names exactly one category
  (`general` or an ambiguous reply → generic). The category is shown in the
  report stats.
- **Huge unformatted English text at the top of the report**: it was the
  "Search" statistic filled with page text by a mis-parsed web_search row
  (TOON `\"` escapes). Fixed in `src/runtime/toon_encode.py`; the stat now
  only accepts short provider ids (`tavily`, `brave`, `searxng`). The "Model"
  stat shows the model actually called (default LLM provider), not
  `AION_MODEL`.
- **The model calls `tool_search('trigger_research')` or says the tool is
  missing**: the tools are resident whenever they are allowed; if they are
  missing the profile has no connector and the chat is not in Deep Research
  mode (see [Availability rules](#availability-rules)).

---

## REST API Reference

All endpoints are authenticated using chat token identity (the `X-AION-User-Id` header only counts in open mode or from the trusted BFF):

### 1. Start & Cancel Jobs
- **`POST /research/start`**
  - **Payload**:
    ```json
    {
      "query": "Topic string",
      "max_rounds": 0,
      "max_time": 300,
      "category": "comparison",
      "session_id": "optional-custom-id",
      "chat_session_id": "optional-chat-session-id"
    }
    ```
  - **Returns**: `{"session_id": "rp-xyz", "status": "running", "query": "..."}`
- **`POST /research/cancel/{session_id}`**
  - **Returns**: `{"cancelled": true}`

### 2. Check Status & SSE Progress
- **`GET /research/enabled`**
  - **Returns**: `{"enabled": true}`
- **`GET /research/active`**
  - **Query parameters**: `chat_session_id` (optional)
  - **Returns**: A list of running research jobs for the current user owner.
- **`GET /research/status/{session_id}`**
  - **Returns**:
    ```json
    {
      "status": "running",
      "progress": {
        "phase": "reading",
        "round": 2,
        "label": "Reading sources...",
        "ts": 17822929.0
      },
      "activities": [ ... ],
      "query": "Topic",
      "started_at": 17822900.0,
      "chat_session_id": "chat-xyz"
    }
    ```
- **`GET /research/stream/{session_id}`**
  - **Type**: `text/event-stream` (SSE)
  - **Returns**: A continuous stream of progress payloads (`data: {...}\n\n`) until completion, ending with a `final: true` event.

### 3. Retrieve Results & HTML Reports
- **`GET /research/report/{session_id}`**
  - **Returns**: An `HTMLResponse` containing the visual report page.
- **`GET /research/detail/{session_id}`**
  - **Returns**: The raw JSON payload containing the synthesized Markdown, stats, and sources.
- **`POST /research/result-peek/{session_id}`**
  - **Returns**: The current draft report without marking it as consumed.
- **`POST /research/result/{session_id}`**
  - **Returns**: Returns the final report content and marks it as consumed (prevents multiple agents from reading the same report).

### 4. Library Management
- **`GET /research/library`**
  - **Query parameters**: `search` (filter), `sort` (`recent`, `oldest`, `alpha`), `limit`, `archived` (boolean), `chat_session_id`.
  - **Returns**: `{"research": [ ... ], "total": N}`
- **`POST /research/{session_id}/archive`**
  - **Query parameters**: `archived=true` or `archived=false`
  - **Returns**: `{"ok": true, "id": "session_id", "archived": true}`
- **`DELETE /research/{session_id}`**
  - **Returns**: `{"deleted": true}`

### 5. Media Concealment in HTML Reports
- **`POST /research/{session_id}/hide-image`**
  - **Payload**: `{"url": "image-url-to-hide"}`
  - **Returns**: `{"ok": true}`
- **`POST /research/{session_id}/unhide-images`**
  - **Returns**: `{"ok": true}` (unhides all images in the report)

---

## UI Integration

The Chat UI integrates deep research tightly to provide a premium user experience:

- **Violet Mode Switcher**: Users can explicitly toggle the chat input mode to **Deep Research**. This instructs the backend and frontend to use the deep research execution pipeline.
- **Research Panel / Dock**: Clicking a research progress anchor link `[topic](#research-{session_id})` in the chat feed intercepts the navigation and slides open a dedicated research dock on the right side of the screen.
- **SSE Progress Feed**: Inside the dock, the application streams real-time activities (e.g., planning, reading specific URLs, synthesis) directly from `/research/stream/{session_id}`.
- **Dynamic HTML Report**: Upon completion, the dock displays a button to open the full HTML report. This report includes:
  - Sticky table of contents (TOC) navigation sidebar.
  - Harmony layout with light/dark theme synchronization.
  - Image carousel showing open graph (OG) previews and scraped visual elements.
  - Print-to-PDF styles optimization (`window.print()` outputs a clean executive brief).
- **Research Library**: Accessible at `/research`, it displays all past completed reports, allowing users to search, sort, archive, or delete them.

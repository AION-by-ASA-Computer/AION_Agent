# Orchestration and HITL planning (Markdown-first)

**Tool availability:** orchestration tools (`draft_execution_plan`, `list_session_execution_plans`, `get_execution_plan`, `update_execution_plan`, `mark_task_completed`) are **built-in** on every profile (`merge_builtin_orchestration_tools` in `src/main.py`) — do **not** add `orchestration` to profile YAML `mcp_servers`. In **Plan Mode** (tool-first, default): **`draft_execution_plan` stays available** — it is how the sidebar plan is created. `mark_task_completed`, `update_execution_plan`, and sandbox writes stay blocked until **Approve Plan**. Do **not** add `draft_execution_plan` to `AION_PLAN_MODE_BLOCKED_TOOLS` when `AION_PLAN_MODE_TOOL_FIRST=1`. `plan_id` is the sidebar id (e.g. `execution_plan_7f2c55`). UI: **Mark all complete** in the Plan dock.

## Single source of truth (DB, not workspace)

- Approved plan and checkbox progress live in **SQLite** (`execution_plans`), updated by `mark_task_completed` and the sidebar.
- **Do not** use `sandbox_fnmatch_glob`, `sandbox_grep_content`, or `sandbox_read_text_file` on `execution_plan_*.md` — those workspace paths **no longer exist** (Cursor-style model).
- Turn context often includes `### EXECUTION PLAN` with the active `plan_id`; if unsure: **`list_session_execution_plans()`** (no session arg: uses current chat).
- **`get_execution_plan()`** without `plan_id` → **active** plan (most recent approved for the session).
- **`mark_task_completed(task_id=...)`** without `plan_id` → same active plan.
- After each task: output shows **how many steps remain** and a numbered list (id + title).
- To edit goal/context/tasks: **`update_execution_plan(plan_id, plan_markdown)`** (full markdown).
- `orchestration_plan_approved` / `internal_trigger` messages include a `## Tasks` snapshot.

Use this checklist in strict order.

## Mandatory anti-token-waste rules

- Never include JSON, raw tool payloads, pseudo-code, or code blocks in reasoning.
- Never simulate tool calls in plain text: call tools directly.
- The plan shown to the user must be **structured Markdown** with fixed sections (Goal / Context / Tasks / Notes).
- Keep reasoning short and action-oriented **outside the plan**. Inside the plan, be thorough (see below).

## 🚫 FORBIDDEN: Milestone/sub-task patterns

**DO NOT** create tasks that are "containers" or "umbrellas" with implicit sub-steps. Every task line must represent **exactly one concrete, atomic action** that can be completed in a single agent turn.

### ❌ BAD (milestone with sub-points — FORBIDDEN):
```
## Tasks
- [ ] `task_01` **Project setup** (deps: none)
- [ ] `task_02` **API implementation** (deps: task_01)
- [ ] `task_03` **React frontend** (deps: task_02)
- [ ] `task_04` **Testing and deploy** (deps: task_03)
```
Each of these is a vague milestone that hides 5-10 real actions. Useless for tracking.

### ✅ GOOD (atomic, one action per task — REQUIRED):
```
## Tasks
- [ ] `task_01` **Create project structure with src/, tests/, docs/ folders** (deps: none)
- [ ] `task_02` **Write requirements.txt with FastAPI, SQLAlchemy, pytest** (deps: task_01)
- [ ] `task_03` **Implement User model in src/models/user.py with id, email, password_hash fields** (deps: task_02)
- [ ] `task_04` **Create Alembic migration for users table** (deps: task_03)
- [ ] `task_05` **Implement POST /auth/register endpoint in src/api/auth.py** (deps: task_04)
- [ ] `task_06` **Implement POST /auth/login with JWT in src/api/auth.py** (deps: task_05)
- [ ] `task_07` **Write unit tests for User model in tests/test_models.py** (deps: task_06)
- [ ] `task_08` **Write integration tests for /auth/register in tests/test_auth.py** (deps: task_06)
- [ ] `task_09` **Configure CORS middleware in src/main.py** (deps: task_01)
```

**Key rule:** If you can say "task X involves doing A, then B, then C", split it into three separate tasks. The goal is granular tracking.

## 🔑 CRITICAL: Document your reasoning IN THE PLAN

The `## Goal` and `## Context` sections are where you **show your work**. The user must understand WHY you chose this approach. Be verbose here.

### ❌ BAD (too terse — the user learns nothing):
```
## Goal
Create a REST API for user management.

## Context
Standard CRUD. JWT auth.
```

### ✅ GOOD (thorough reasoning — user can evaluate your thinking):
```
## Goal
Build a REST API for user management with registration, JWT login, and profile CRUD, persisting data to SQLite via async SQLAlchemy.

## Context
- **Chosen stack:** FastAPI (async), SQLAlchemy 2.0 (async), SQLite (local dev), pytest for tests
- **Constraints:** API must run on port 8001 and share the agent's event loop
- **Auth:** JWT with secret from environment variable, 24h token expiry, no refresh required in this phase
- **Risks:** User model must stay backward compatible with the existing profile system — verify after task_03
- **Out of scope:** No frontend, no Docker, no social login — pure REST API only
- **Acceptance criteria:**
  1. POST /auth/register returns 201 with user JSON (no password)
  2. POST /auth/login returns 200 with JWT token
  3. GET /users/me returns the authenticated user's profile
  4. All tests pass with `pytest -v`
```

**Rule of thumb for Context:** Include stack, constraints, risks, explicit "do not do" boundaries, and verifiable acceptance criteria. This is where the user judges your plan quality.

## Canonical `<plan>` shape (must match server parsing)

The runtime parses plans with `markdown_to_plan` (`src/a2a/plan_markdown.py`). Follow **exactly** this skeleton inside `<plan> … </plan>`:

```markdown
<plan>
# Execution Plan

## Goal
[One or more sentences describing the verifiable objective. Be specific about WHAT, not HOW.]

## Context
[THOROUGH documentation of your reasoning:
- Architecture decisions and their rationale
- Constraints (technical, time, scope)
- Risks and mitigation strategies
- Explicit "out of scope" items
- Acceptance criteria (verifiable, testable)
- Any assumptions you're making]

## Tasks
- [ ] `task_01` **First concrete atomic action** (deps: none)
- [ ] `task_02` **Second concrete atomic action** (deps: task_01)
- [ ] `task_03` **Third action — note: ONE action, not a chapter** (deps: task_01)
- [ ] `task_04` **Fourth action — task_03 and task_02 are independent** (deps: task_02)
- [ ] `task_05` **Each task is verifiable on its own** (deps: none)
- [ ] `task_06` **Penultimate action — always atomic** (deps: task_04, task_03)

## Notes
[Any additional context for the reviewer, open questions, or implementation notes.]
</plan>
```

### Critical formatting rules

1. **One line per task** under `## Tasks`, starting with `- [ ]` (unchecked). Dependencies are reflected after backend/mark_task_completed as `- [x]` for completed ids — you still emit `- [ ]` when authoring.
2. **Do not** add indented `- Description:` lines under tasks; put prose in **`## Context`** or **`## Notes`**. (Legacy `- Description:` may still parse but is **discouraged** and splits poorly with block editors.)
3. **`deps`** on the same line as the task: `(deps: none)` or `(deps: task_01, task_02)`. Do **not** add per-task `profile` — execution uses the session agent only.
4. `deps` values: `none` (or `-`) for no dependencies, or comma-separated task IDs.
5. **`## Deliverable`** — single `workspace/*.md` path for markdown document plans; all writing tasks after the first must use `sandbox_edit_workspace_file`.
5. `# Execution Plan` is preferred; `# Plan` is acceptable as the top heading before sections.
6. **Atomicity check:** Every task title must describe a single tool call or a single file edit. If the title contains "and" connecting two distinct actions, split it.

## Plan Mode (tool-first, default)

When the system declares **PLAN MODE** active:

- **Do not** run `skill_view`, long `web_search` series, or deliverable generation in the planning turn.
- **Do** call **`draft_execution_plan(goal, tasks)`** once with a **required** `tasks` JSON array (`task_01`, `task_02`, …). Minimum **6 atomic tasks** for non-trivial / strategic requests. Chat: only a 2–3 line summary.
- **Never** register a single catch-all task titled `main` or dump the whole goal into one task — the server rejects degenerate plans.
- **Budget:** at most 2 read-only tools before registering (`AION_PLAN_MODE_MAX_RESEARCH_TOOLS`). Which tools count: `AION_PLAN_MODE_RESEARCH_TOOLS`.
- Put thorough reasoning in the tool's `goal` string and each task `title` (stack, risks, acceptance criteria) — not in extended chat prose without structured tasks.
- **Legacy fallback** (`AION_PLAN_TEXT_PARSER=1` only): emit one complete `<plan>` block (sections below), then stop.

## Workflow

1. **Understand the objective**
   - Analyze the request deeply. What is the real outcome the user wants?
   - Identify constraints, risks, and what NOT to do.
   - Summarize the goal in a clear, verifiable sentence (under `## Goal`).
   - Document ALL your reasoning, architecture decisions, and rationale under `## Context`.

2. **Create a detailed, atomic plan**
   - **Tool-first (default):** call **`draft_execution_plan`** with `goal` + `tasks` JSON (see above). This is the primary path.
   - **Legacy text parser only:** write a complete `<plan> ... </plan>` block (intercepted by runtime).
   - Minimum quality requirements:
     - **at least 6 atomic tasks** for non-trivial requests (each a single action);
     - each task title names **one concrete, verifiable action** (file path, function name, specific operation);
     - explicit dependencies (`deps: task_XX` or `deps: none`);
     - the `## Context` section must be thorough (3+ lines covering architecture, constraints, risks, acceptance criteria);
     - NEVER create "container" tasks (milestones) — every line is one action.

3. **Wait for human approval**
   - After producing `<plan>`, stop your response.
   - Wait for explicit confirmation from the user before execution.

4. **Execute step-by-step (single agent)**
   - At the start of post-approval execution: `list_session_execution_plans()` or `get_execution_plan()` to confirm `plan_id` and pending tasks.
   - Execute **one task per agent turn** — the runtime stops the turn after `mark_task_completed`.
   - Markdown deliverable: path in `## Deliverable`; create once, then **only** `sandbox_edit_workspace_file`.
   - At task completion, call `mark_task_completed(task_id=...)` then **STOP** (next task runs in a new turn).
   - Do not proceed to the next task in the same response.

5. **Tracking and quality**
   - Respect dependency order.
   - After each task, record outcome (ok/fail, evidence, next step).
   - On failure, update the plan with explicit remediation (still via Markdown sections above).

6. **Close**
   - Summarize outcome against original goal.
   - List residual risks and recommended checks.
   - Reply in the same language used by the user unless explicitly requested otherwise.

## Operational infra (Redis / Approve Plan)

The **Approve Plan** button (chat-ui) updates HITL state on **Redis** (same mechanism as `set_pending` when the plan is created). If Redis is unreachable, the URL is wrong, or you run multiple workers without shared Redis, the API may return **503** (Redis error) or **400** (`plan_not_found_or_expired` with an explanatory message).

- **Single backend process (dev):** `AION_REDIS_FALLBACK_LOCAL=1` uses an in-memory queue instead of Redis; do not scale horizontally that way.
- **Compose / LAN:** align `AION_REDIS_URL` (e.g. `redis://redis:6379/0` on the Docker bridge, `redis://127.0.0.1:6379/0` locally).
- **Diagnostics:** in logs look for `plan_wait set_pending FAILED`, `resolve_plan: Redis GET failed`, and in Admin → System check Redis / LocalFallback status.

The backend automatically strips a `<plan>...</plan>` wrapper from markdown before approval parsing, as long as `## Goal` / `## Tasks` sections remain in the expected format inside.

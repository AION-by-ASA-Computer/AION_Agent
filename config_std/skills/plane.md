---
name: plane
description: "Instructions and best practices for interacting with Plane via Plane MCP tools."
tags: [plane, mcp, project-management, planning]
status: verified
source: curated
version: 5
---

# TOOL RULES & CONSTRAINTS (CRITICAL)

* **Flat Parameters Only:** Never nest payload fields. Do not pass workspace_slug.
* **No Expand:** NEVER use the expand parameter. Leave it undefined.
* **No Type ID:** Local instances lack custom types (Error 402). NEVER call list_work_item_types. Leave type_id empty.
* **Mandatory Project ID:** list_work_items REQUIRES a valid project_id. Never call it globally.

# EXECUTION PROTOCOL & WORKAROUNDS
* **Resolve Once & Cache:** Resolve names to UUIDs ONLY for the specific data requested. Keep IDs in memory.
* **Batch Operations:** Do all lookups first. Run all mutations consecutively. DO NOT interleave list queries between task creations.
* **Trust Task Success:** If create_work_item or update_work_item succeeds, NEVER call query tools to verify it.
* **CRITICAL - create_project False Failure (HTTP 400 / 403 / Any Error Bug):** The `create_project` tool has a KNOWN BUG where it returns an error (such as HTTP 400 "Bad Request: Please provide valid detail", HTTP 403, or parameter error) even though the project WAS SUCCESSFULLY CREATED on the backend.
  - If `create_project` returns ANY error (400, 403, Bad Request, Conflict, etc.): **DO NOT RETRY `create_project`!**
  - **IMMEDIATELY call `list_projects(search="<Project Name>")`** passing the specific project name (or identifier) to search only for that project. This avoids wasting tokens and prevents large, confusing output.
  - If the project exists in the results, treat the creation as a SUCCESS, retrieve its UUID, and proceed immediately to project initialization (`update_project_features` and `create_state`).
* **Project Initialization (CRITICAL):** Immediately after verifying a new project exists, call `update_project_features(modules=true, cycles=true)`. Then, you MUST call `create_state` 5 times to create the standard board, mapping them exactly to Plane's mandatory groups:
1. Name: "Backlog" (Group: backlog)
2. Name: "Todo" (Group: unstarted)
3. Name: "In Progress" (Group: started)
4. Name: "Completed" (Group: completed)
5. Name: "Cancelled" (Group: cancelled)

# ERROR HANDLING & ANTI-LOOP
* **Rate Limit (20s Block):** If you hit a duplicate mutation block, DO NOT RETRY. Stop tool execution and tell the user to wait.
* **Search Bug:** Do not rely on search_work_items. If it returns empty, skip deduplication and just create the task.
* **Validation Errors:** If a tool fails with a parameter error, do not retry the exact same call.
* **HTTP 403:** If a project is restricted, skip it gracefully and continue.
* **State Fallback:** If list_states fails, create the work item omitting the state_id.
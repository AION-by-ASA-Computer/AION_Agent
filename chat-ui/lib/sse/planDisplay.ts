/** Hide raw `<plan>...</plan>` from chat timeline (sidebar owns the plan UI). */

const PLAN_BLOCK_RE = /<plan\b[^>]*>[\s\S]*?<\/plan>/gi;
const PLAN_OPEN_RE = /<plan\b/i;
const PLAN_PSEUDO_OPEN_RE = /(?:^|\n)\s*plan\s+title\s*=/i;
const PLAN_CLOSE_RE = /<\/plan>/i;
const PLAN_MARKDOWN_BODY_RE =
  /(?:^|\n)\s*(?:#+\s*piano\b|##\s*(?:task|tasks|goal|obiettivo)\b|\*\*task_\d+)/i;

export type PlanCapturePhase = "none" | "open_tag" | "body";

/** Earliest canonical or pseudo plan opener (models often omit `<`). */
function findPlanOpenIndex(text: string): number {
  const direct = text.search(PLAN_OPEN_RE);
  const pseudo = text.search(PLAN_PSEUDO_OPEN_RE);
  if (direct < 0 && pseudo < 0) return -1;
  if (direct < 0) return pseudo;
  if (pseudo < 0) return direct;
  return Math.min(direct, pseudo);
}

/** Earliest plan content: XML tag, pseudo opener, or markdown-only plan body. */
function findPlanContentIndex(text: string): number {
  const tag = findPlanOpenIndex(text);
  const md = text.search(PLAN_MARKDOWN_BODY_RE);
  if (tag < 0 && md < 0) return -1;
  if (tag < 0) return md;
  if (md < 0) return tag;
  return Math.min(tag, md);
}

const PARTIAL_OPEN_MARKERS = [
  "<plan title=",
  "<plan title",
  "<plan titl",
  "<plan tit",
  "<plan ti",
  "<plan t",
  "<plan ",
  "<plan",
  "plan title=",
  "plan title",
  "plan titl",
  "plan tit",
  "plan ti",
  "plan t",
  "plan ",
  "plan",
];

/** Partial plan opener prefix at end of buffer (streaming). */
function trailingPartialPlanOpen(text: string): number {
  let best = 0;
  for (const marker of PARTIAL_OPEN_MARKERS) {
    const maxKeep = marker.length - 1;
    for (let keep = maxKeep; keep >= 1; keep -= 1) {
      if (text.endsWith(marker.slice(0, keep))) {
        best = Math.max(best, keep);
        break;
      }
    }
  }
  return best;
}

/** Partial `</plan` prefix at end while inside a plan block. */
function trailingPartialPlanClose(text: string): number {
  const marker = "</plan>";
  const maxKeep = marker.length - 1;
  for (let keep = maxKeep; keep >= 1; keep -= 1) {
    if (text.endsWith(marker.slice(0, keep))) {
      return keep;
    }
  }
  return 0;
}

/** Consume `<plan ...>` or pseudo `plan title="..."` opener; returns false if incomplete. */
function consumePlanOpenTag(rest: string): { consumed: number; complete: boolean } {
  const gt = rest.indexOf(">");
  if (gt >= 0) return { consumed: gt + 1, complete: true };

  // Models often omit `>` before the markdown body: title="..." then newline.
  const quotedNewline = rest.match(/^[\s\S]*?"\s*(?:\r?\n|$)/);
  if (quotedNewline) {
    return { consumed: quotedNewline[0].length, complete: true };
  }

  return { consumed: 0, complete: false };
}

export function stripPlanBlocksForChatDisplay(text: string): string {
  if (!text) return "";
  let out = text.replace(PLAN_BLOCK_RE, "");
  // Unclosed pseudo opener: hide from `plan title=` through end of message.
  out = out.replace(/(?:^|\n)\s*plan\s+title\s*=[\s\S]*$/i, "");
  // Unclosed `<plan ...>` (missing `>` or `</plan>`).
  out = out.replace(/<plan\b[\s\S]*$/i, "");
  // Orphan attribute fragments from chunked streaming (e.g. `="Title"` after `<plan title`).
  out = out.replace(/(?:^|\n)\s*=\s*"[^"]*"[\s\S]*$/i, "");
  const mdStart = out.search(PLAN_MARKDOWN_BODY_RE);
  if (mdStart >= 0) {
    out = out.slice(0, mdStart).trimEnd();
  }
  return out.trim();
}

export type PlanAwareDisplayResult = {
  display: string;
  phase: PlanCapturePhase;
  pending: string;
  /** @deprecated use phase !== "none" */
  inPlan: boolean;
};

/**
 * Streaming filter: drop tokens inside plan open tag and body until </plan>.
 * Buffers partial open/close suffixes so title attributes and tag names do not leak into chat.
 */
export function feedPlanAwareDisplay(
  piece: string,
  phase: PlanCapturePhase | boolean = "none",
  pending = "",
): PlanAwareDisplayResult {
  const startPhase: PlanCapturePhase =
    typeof phase === "boolean" ? (phase ? "body" : "none") : phase;

  if (!piece && !pending) {
    return { display: "", phase: startPhase, pending: "", inPlan: startPhase !== "none" };
  }

  let rest = pending + piece;
  let pendingOut = "";
  let out = "";
  let currentPhase = startPhase;

  while (rest.length > 0) {
    if (currentPhase === "none") {
      const open = findPlanContentIndex(rest);
      if (open < 0) {
        const partial = trailingPartialPlanOpen(rest);
        if (partial > 0) {
          out += rest.slice(0, rest.length - partial);
          pendingOut = rest.slice(-partial);
        } else {
          out += rest;
        }
        rest = "";
        break;
      }
      out += rest.slice(0, open);
      rest = rest.slice(open);
      const viaTag = findPlanOpenIndex(rest) === 0;
      currentPhase = viaTag ? "open_tag" : "body";
      continue;
    }

    if (currentPhase === "open_tag") {
      const tag = consumePlanOpenTag(rest);
      if (!tag.complete) {
        pendingOut = rest;
        rest = "";
        break;
      }
      rest = rest.slice(tag.consumed);
      currentPhase = "body";
      continue;
    }

    const close = rest.search(PLAN_CLOSE_RE);
    if (close < 0) {
      const partial = trailingPartialPlanClose(rest);
      if (partial > 0) {
        pendingOut = rest.slice(-partial);
        rest = rest.slice(0, rest.length - partial);
      }
      rest = "";
      break;
    }
    rest = rest.slice(close + "</plan>".length);
    currentPhase = "none";
  }

  return {
    display: out,
    phase: currentPhase,
    pending: pendingOut,
    inPlan: currentPhase !== "none",
  };
}

/** Best-effort plan body while streaming (for dock preview). */
export function extractStreamingPlanMarkdown(assistantContent: string): string {
  if (!assistantContent) return "";
  const openIdx = findPlanContentIndex(assistantContent);
  if (openIdx < 0) return "";
  let body = assistantContent.slice(openIdx);
  body = body.replace(/^<plan\b[^>]*>\s*/i, "");
  body = body.replace(/^<plan\b[\s\S]*?"\s*(?:\r?\n|$)/i, "");
  body = body.replace(/^(?:plan\s+title\s*=[^\n]*\n?)/i, "");
  body = body.replace(/<\/plan>\s*$/i, "");
  return body.trim();
}

/** SSOT plan payload from orchestration DB (tool-first / SSE). */
export type OrchestrationPlanTask = {
  id: string;
  title: string;
  description?: string;
  depends_on?: string[];
  target_profile?: string | null;
};

export type OrchestrationPlanPayload = {
  goal: string;
  tasks: OrchestrationPlanTask[];
  context?: string;
};

export type OrchestrationPlanPendingEvent = {
  type: "orchestration_plan_pending";
  plan_id: string;
  plan: OrchestrationPlanPayload;
  plan_markdown?: string;
  revision?: number;
  goal?: string;
  force_sidebar_refresh?: boolean;
};

export type PlanPhaseEvent = {
  type: "plan_phase";
  phase: string;
  plan_id?: string;
  message?: string;
};

export type PlanErrorEvent = {
  type: "plan_error";
  plan_id: string;
  message: string;
};

/** Prefer structured plan JSON from orchestration; skip markdown re-parse when present. */
export function planFromOrchestrationEvent(
  evt: OrchestrationPlanPendingEvent,
): OrchestrationPlanPayload | null {
  if (!evt?.plan_id) return null;
  return normalizePlanPayload(evt.plan);
}

export function isOrchestrationPlanEvent(
  evt: { type?: string },
): evt is OrchestrationPlanPendingEvent {
  return evt?.type === "orchestration_plan_pending" && Boolean((evt as OrchestrationPlanPendingEvent).plan_id);
}

const CANONICAL_TASK_LINE_RE = /^\s*-\s*\[[ xX]\]\s*`[^`]+`/m;

/** True when markdown is empty, raw JSON, or missing canonical task checkboxes. */
export function isUnusablePlanMarkdown(md: string): boolean {
  const s = (md || "").trim();
  if (!s) return true;
  if (s.startsWith("[") || (s.startsWith("{") && s.includes('"tasks"'))) {
    try {
      const parsed = JSON.parse(s) as unknown;
      if (Array.isArray(parsed)) return true;
      if (parsed && typeof parsed === "object" && "tasks" in (parsed as object)) return true;
    } catch {
      if (s.startsWith("[")) return true;
    }
  }
  if (!CANONICAL_TASK_LINE_RE.test(s)) {
    const hasTasksHdr = /^##\s*(tasks?|compiti|passi|steps?|tareas)/im.test(s);
    const taskCount = (s.match(/^\s*-\s*\[[ xX]\]/gm) || []).length;
    if (hasTasksHdr && taskCount === 0) return true;
    if (!hasTasksHdr && /^\s*\[/.test(s)) return true;
  }
  return false;
}

function normalizePlanPayload(plan: unknown): OrchestrationPlanPayload | null {
  if (!plan || typeof plan !== "object") return null;
  const p = plan as Record<string, unknown>;
  let tasks = p.tasks;
  if (typeof tasks === "string") {
    try {
      tasks = JSON.parse(tasks) as unknown;
    } catch {
      tasks = [];
    }
  }
  if (!Array.isArray(tasks) || tasks.length === 0) return null;
  const out: OrchestrationPlanTask[] = [];
  for (const row of tasks) {
    if (!row || typeof row !== "object") continue;
    const t = row as Record<string, unknown>;
    out.push({
      id: String(t.id || `task_${String(out.length + 1).padStart(2, "0")}`),
      title: String(t.title || "Untitled"),
      description: t.description ? String(t.description) : undefined,
      depends_on: Array.isArray(t.depends_on) ? (t.depends_on as string[]) : undefined,
      target_profile: t.target_profile != null ? String(t.target_profile) : null,
    });
  }
  if (!out.length) return null;
  return {
    goal: String(p.goal || "Execution plan"),
    context: p.context ? String(p.context) : undefined,
    tasks: out,
  };
}

/** Canonical markdown from structured plan JSON (SSOT — no re-parse of chat stream). */
export function orchestrationPlanToMarkdown(
  plan: OrchestrationPlanPayload,
  labels?: { title?: string; goal?: string; context?: string; tasks?: string; notes?: string },
): string {
  const title = labels?.title || "Execution Plan";
  const goalHdr = labels?.goal || "Goal";
  const ctxHdr = labels?.context || "Context";
  const tasksHdr = labels?.tasks || "Tasks";
  const notesHdr = labels?.notes || "Notes";
  const lines = [`# ${title}`, "", `## ${goalHdr}`, plan.goal || title];
  if (plan.context?.trim()) {
    lines.push("", `## ${ctxHdr}`, plan.context.trim());
  }
  lines.push("", `## ${tasksHdr}`);
  for (const task of plan.tasks || []) {
    const deps =
      Array.isArray(task.depends_on) && task.depends_on.length
        ? task.depends_on.join(", ")
        : "none";
    const id = task.id || "task_id";
    const taskTitle = task.title || "Untitled";
    lines.push(`- [ ] \`${id}\` **${taskTitle}** (deps: ${deps})`);
    const desc = (task.description || "").trim();
    if (desc) {
      lines.push(`  - Description: ${desc}`);
    }
  }
  lines.push("", `## ${notesHdr}`, "- Edit tasks in the sidebar, then approve.");
  return lines.join("\n");
}

/** Prefer structured plan JSON when markdown is missing or non-canonical. */
export function resolvePlanEditorMarkdown(
  markdown: string | undefined | null,
  plan: OrchestrationPlanPayload | unknown,
  labels?: Parameters<typeof orchestrationPlanToMarkdown>[1],
): string {
  const structured = normalizePlanPayload(plan);
  const md = (markdown || "").trim();
  if (structured) {
    if (isUnusablePlanMarkdown(md)) {
      return orchestrationPlanToMarkdown(structured, labels);
    }
    const mdTasks = (md.match(/^\s*-\s*\[[ xX]\]\s*`[^`]+`/gm) || []).length;
    if (mdTasks === 0 && structured.tasks.length > 0) {
      return orchestrationPlanToMarkdown(structured, labels);
    }
  }
  if (md && !isUnusablePlanMarkdown(md)) return md;
  if (structured) return orchestrationPlanToMarkdown(structured, labels);
  return md;
}

/** Normalize SSE/localStorage chunk: prefer structured plan over markdown round-trip. */
export function normalizePlanPendingChunk(
  chunk: OrchestrationPlanPendingEvent & Record<string, unknown>,
): OrchestrationPlanPendingEvent {
  const structured = planFromOrchestrationEvent(chunk);
  if (!structured) return chunk;
  const md = resolvePlanEditorMarkdown(
    chunk.plan_markdown ? String(chunk.plan_markdown) : "",
    structured,
  );
  return {
    ...chunk,
    plan: structured,
    plan_markdown: md,
    goal: chunk.goal || structured.goal,
  };
}

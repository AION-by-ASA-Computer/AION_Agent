"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  Plus,
  Trash2,
  XCircle,
} from "lucide-react";
import {
  fetchPlanExecutionResult,
  subscribePlanExecutionStream,
  type PlanExecutionActivity,
  type PlanExecutionProgress,
} from "@/lib/api/plan-execution";
import {
  orchestrationPlanToMarkdown,
  type OrchestrationPlanPayload,
  type OrchestrationPlanTask,
} from "@/lib/sse/planDisplay";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

// ─── local helpers ────────────────────────────────────────────────────────────

function nextTaskId(tasks: LocalTask[]): string {
  let max = 0;
  for (const t of tasks) {
    const m = t.id.match(/^task_(\d+)$/);
    if (m) max = Math.max(max, parseInt(m[1], 10));
  }
  return `task_${String(max + 1).padStart(2, "0")}`;
}

function payloadFromLocal(tasks: LocalTask[], goal: string, context: string): OrchestrationPlanPayload {
  return {
    goal: goal.trim(),
    context: context.trim() || undefined,
    tasks: tasks.map((t) => ({
      id: t.id.trim(),
      title: t.title.trim(),
      description: t.description.trim() || undefined,
      depends_on: t.depsRaw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    })),
  };
}

function activityIcon(act: PlanExecutionActivity, isLatest: boolean) {
  if (act.phase === "error") return <XCircle className="mt-0.5 h-3 w-3 shrink-0 text-destructive" />;
  if (isLatest) return <Loader2 className="mt-0.5 h-3 w-3 shrink-0 animate-spin text-primary" />;
  return <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-500/80" />;
}

// ─── types ────────────────────────────────────────────────────────────────────

type LocalTask = {
  /** stable UI key */
  key: string;
  id: string;
  title: string;
  description: string;
  depsRaw: string;
};

function toLocalTasks(tasks: OrchestrationPlanTask[]): LocalTask[] {
  return (tasks || []).map((t, i) => ({
    key: `${t.id || i}-${i}`,
    id: t.id || `task_${String(i + 1).padStart(2, "0")}`,
    title: t.title || "",
    description: t.description || "",
    depsRaw: (t.depends_on || []).join(", "),
  }));
}

// ─── component ────────────────────────────────────────────────────────────────

export type PlanEditorProps = {
  apiBase: string;
  planId: string;
  sessionId: string;
  initialPlan: OrchestrationPlanPayload;
  initialMarkdown?: string;
  revision?: number;
  authToken?: string | null;
  userId?: string;
  profileName?: string;
  highlightTaskId?: string;
  executionRunId?: string | null;
  onPlanApproved?: (runId: string, planId: string) => void;
  onFinalSummary?: (summary: string, planId: string, runId?: string) => void;
  onExecutionAdoptHandled?: () => void;
};

export function PlanEditor({
  apiBase,
  planId,
  sessionId,
  initialPlan,
  revision,
  authToken,
  userId,
  profileName,
  highlightTaskId: hlProp,
  executionRunId,
  onPlanApproved,
  onFinalSummary,
  onExecutionAdoptHandled,
}: PlanEditorProps) {
  const t = useT();

  const [goal, setGoal] = useState(initialPlan?.goal || "");
  const [context, setContext] = useState(initialPlan?.context || "");
  const [tasks, setTasks] = useState<LocalTask[]>(() => toLocalTasks(initialPlan?.tasks || []));

  const [isLocked, setIsLocked] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");
  const [userDecision, setUserDecision] = useState<"approved" | "rejected" | null>(null);

  // execution progress state
  const [execLabel, setExecLabel] = useState("");
  const [execStatus, setExecStatus] = useState("");
  const [execActivities, setExecActivities] = useState<PlanExecutionActivity[]>([]);
  const [execDeliverablePath, setExecDeliverablePath] = useState<string | null>(null);
  const [execExpanded, setExecExpanded] = useState(true);

  const [hlTask, setHlTask] = useState((hlProp || "").trim());
  const [lastAppliedRevision, setLastAppliedRevision] = useState(0);
  const [revisionNotice, setRevisionNotice] = useState("");
  const [showMarkdown, setShowMarkdown] = useState(false);

  const planId_ = (planId || "").trim();
  const sessionId_ = (sessionId || "").trim();
  const base = (apiBase || "").replace(/\/$/, "");

  const buildHeaders = useCallback(() => {
    const h: Record<string, string> = {
      "Content-Type": "application/json",
      "X-AION-User-Id": userId || "default",
    };
    if (authToken) h.Authorization = `Bearer ${authToken}`;
    return h;
  }, [userId, authToken]);

  // sync plan from SSE / prop updates (revision-guarded)
  useEffect(() => {
    const incomingRev = Number(revision || 1);
    if (incomingRev <= lastAppliedRevision) return;
    setGoal(initialPlan?.goal || "");
    setContext(initialPlan?.context || "");
    setTasks(toLocalTasks(initialPlan?.tasks || []));
    setLastAppliedRevision(incomingRev);
    if (incomingRev > 1) setRevisionNotice(t("plan.notice.updated", { rev: incomingRev }));
  }, [initialPlan, revision, t, lastAppliedRevision]);

  // highlight task sync
  useEffect(() => {
    const h = (hlProp || "").trim();
    if (h) setHlTask(h);
  }, [hlProp]);

  const executionFinalHandledRef = useRef(false);
  const onFinalSummaryRef = useRef(onFinalSummary);
  const onExecutionAdoptHandledRef = useRef(onExecutionAdoptHandled);

  useEffect(() => {
    onFinalSummaryRef.current = onFinalSummary;
  }, [onFinalSummary]);

  useEffect(() => {
    onExecutionAdoptHandledRef.current = onExecutionAdoptHandled;
  }, [onExecutionAdoptHandled]);

  useEffect(() => {
    executionFinalHandledRef.current = false;
  }, [executionRunId]);

  // execution stream subscription
  useEffect(() => {
    const runId = (executionRunId || "").trim();
    if (!runId || !userId) return;
    setIsLocked(true);
    setExecExpanded(true);
    let cancelled = false;

    const unsub = subscribePlanExecutionStream(
      runId,
      userId,
      authToken,
      (ev: PlanExecutionProgress) => {
        if (cancelled) return;
        const label = ev.label || ev.message || "";
        if (label) setExecLabel(label);
        if (ev.status) setExecStatus(ev.status);
        if (ev.task_id) setHlTask(String(ev.task_id));
        if (ev.activities?.length) {
          setExecActivities(ev.activities);
        } else if (label) {
          setExecActivities((prev) =>
            [
              ...prev,
              { label, message: ev.message, task_id: ev.task_id, ts: Date.now() / 1000 },
            ].slice(-50),
          );
        }
        if (ev.error) {
          setExecLabel(ev.error);
          setExecStatus("error");
        }
      },
      () => {
        if (cancelled || executionFinalHandledRef.current) return;
        executionFinalHandledRef.current = true;
        void (async () => {
          const result = await fetchPlanExecutionResult(runId, userId!, authToken);
          if (result?.deliverable_path) setExecDeliverablePath(result.deliverable_path);
          if (result?.summary) {
            onFinalSummaryRef.current?.(result.summary, result.plan_id || planId_, runId);
          }
          onExecutionAdoptHandledRef.current?.();
        })();
      },
    );

    return () => {
      cancelled = true;
      unsub();
    };
  }, [executionRunId, userId, authToken, planId_]);

  // task actions
  const addTask = useCallback(() => {
    setTasks((prev) => {
      const newId = nextTaskId(prev);
      return [
        ...prev,
        { key: `${newId}-${Date.now()}`, id: newId, title: "", description: "", depsRaw: "" },
      ];
    });
  }, []);

  const removeTask = useCallback((key: string) => {
    setTasks((prev) => prev.filter((t) => t.key !== key));
  }, []);

  const updateTask = useCallback((key: string, patch: Partial<Omit<LocalTask, "key">>) => {
    setTasks((prev) => prev.map((t) => (t.key === key ? { ...t, ...patch } : t)));
  }, []);

  // API calls
  const postDecision = useCallback(
    async (
      path: string,
      body: Record<string, unknown>,
      okText: string,
      decision: "approved" | "rejected",
    ) => {
      setIsSubmitting(true);
      setStatusMsg(t("plan.decision.sending"));
      try {
        const r = await fetch(`${base}${path}`, {
          method: "POST",
          headers: buildHeaders(),
          body: JSON.stringify(body),
        });
        const j = await r.json().catch(() => null);
        if (!r.ok) {
          setStatusMsg(t("plan.error.server", { code: r.status, msg: (j?.detail as string) || "Unknown error" }));
          return;
        }
        if (decision === "approved") setIsLocked(true);
        setUserDecision(decision);
        setStatusMsg(okText);
        if (
          decision === "approved" &&
          typeof onPlanApproved === "function" &&
          j?.run_id
        ) {
          const rid = String(j.run_id || "").trim();
          const pid = String(j.plan_id || planId_ || "").trim();
          if (rid && pid) onPlanApproved(rid, pid);
        }
      } catch (e: unknown) {
        setStatusMsg(t("plan.error.network", { msg: (e as Error).message }));
      } finally {
        setIsSubmitting(false);
      }
    },
    [base, buildHeaders, onPlanApproved, planId_, t],
  );

  const onApprove = useCallback(() => {
    if (!planId_) return;
    const payload = payloadFromLocal(tasks, goal, context);
    const markdown = orchestrationPlanToMarkdown(payload);
    postDecision(
      `/internal/orchestration/plans/${encodeURIComponent(planId_)}/approve`,
      {
        session_id: sessionId_,
        approved_markdown: markdown,
        todos: payload.tasks.map((tk) => ({
          id: tk.id,
          title: tk.title,
          description: tk.description || "",
          status: "pending",
          depends_on: tk.depends_on || [],
          target_profile: "",
          comment: "",
        })),
        annotations: {},
        approve_only: false,
        user_id: userId || undefined,
        profile_name: profileName || undefined,
      },
      t("plan.decision.ok_approved"),
      "approved",
    );
  }, [planId_, sessionId_, tasks, goal, context, userId, profileName, postDecision, t]);

  const onReject = useCallback(() => {
    if (!planId_) return;
    postDecision(
      `/internal/orchestration/plans/${encodeURIComponent(planId_)}/reject`,
      { session_id: sessionId_, reason: "rejected_from_ui" },
      t("plan.decision.ok_rejected"),
      "rejected",
    );
  }, [planId_, sessionId_, postDecision, t]);

  const exportedMarkdown = showMarkdown
    ? orchestrationPlanToMarkdown(payloadFromLocal(tasks, goal, context))
    : null;

  const showFooterActions = userDecision === null && !isLocked;

  return (
    <div className="flex h-full flex-col text-sm">
      {/* header */}
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-card/80 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 shrink-0 rounded-full bg-primary" />
          <span className="font-semibold tracking-tight">{t("plan.title")}</span>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          {isLocked && (
            <span className="rounded-full bg-amber-500/15 px-2 py-0.5 font-medium text-amber-300">
              {t("plan.status.locked")}
            </span>
          )}
          <span>{t("plan.status.revision")} {lastAppliedRevision || revision || 1}</span>
        </div>
      </div>

      {/* revision notice */}
      {revisionNotice && (
        <div className="shrink-0 border-b border-border bg-amber-500/10 px-4 py-1.5 text-[11px] text-amber-300">
          {revisionNotice}
        </div>
      )}

      {/* execution strip */}
      {executionRunId && (
        <div className="shrink-0 border-b border-border bg-muted/30">
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-2 text-left"
            onClick={() => setExecExpanded((v) => !v)}
          >
            {execStatus !== "done" && execStatus !== "error" ? (
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" />
            ) : execStatus === "error" ? (
              <XCircle className="h-3.5 w-3.5 shrink-0 text-destructive" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
            )}
            <span className="flex-1 truncate font-medium text-[12px]">
              {execLabel || t("plan.execution.running")}
            </span>
            {execExpanded ? (
              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
            )}
          </button>
          {execExpanded && (execActivities.length > 0 || execDeliverablePath) && (
            <div className="space-y-1 pb-2 pl-10 pr-4">
              {execDeliverablePath && (
                <p className="text-[11px] text-muted-foreground">
                  <span className="font-medium text-foreground">{t("plan.execution.deliverable")}:</span>{" "}
                  <code className="font-mono text-[10px]">{execDeliverablePath}</code>
                </p>
              )}
              <ul className="max-h-36 space-y-1 overflow-y-auto">
                {execActivities
                  .slice(-12)
                  .reverse()
                  .map((act, idx) => {
                    const label = act.label || act.message || act.phase || "…";
                    const isLatest = idx === 0 && execStatus !== "done" && execStatus !== "error";
                    return (
                      <li
                        key={`${act.ts ?? idx}-${label.slice(0, 40)}`}
                        className={cn(
                          "flex items-start gap-2 text-[11px] leading-snug",
                          isLatest ? "text-foreground" : "text-muted-foreground",
                        )}
                      >
                        {activityIcon(act, isLatest)}
                        <span className="min-w-0 flex-1">{label}</span>
                      </li>
                    );
                  })}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* scrollable body */}
      <div className="min-h-0 flex-1 overflow-y-auto p-4 space-y-5">
        {/* goal */}
        <div className="space-y-1.5">
          <label className="block text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {t("plan.editor.goal_label")}
          </label>
          <input
            type="text"
            disabled={isLocked}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder={t("plan.editor.goal_placeholder")}
            className={cn(
              "w-full rounded-md border border-border bg-background px-3 py-1.5 text-[13px] placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary",
              isLocked && "opacity-60 cursor-not-allowed",
            )}
          />
        </div>

        {/* context */}
        <div className="space-y-1.5">
          <label className="block text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {t("plan.editor.context_label")}
          </label>
          <textarea
            disabled={isLocked}
            value={context}
            onChange={(e) => setContext(e.target.value)}
            placeholder={t("plan.editor.context_placeholder")}
            rows={2}
            className={cn(
              "w-full resize-y rounded-md border border-border bg-background px-3 py-1.5 text-[13px] placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary",
              isLocked && "opacity-60 cursor-not-allowed",
            )}
          />
        </div>

        {/* tasks */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {t("plan.editor.tasks_label")} ({tasks.length})
            </label>
            {!isLocked && (
              <button
                type="button"
                onClick={addTask}
                className="flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-[11px] font-medium hover:bg-muted/80 transition-colors"
              >
                <Plus className="h-3 w-3" />
                {t("plan.editor.add_task")}
              </button>
            )}
          </div>

          <ul className="space-y-3">
            {tasks.map((task, idx) => {
              const isHl = hlTask && task.id === hlTask;
              return (
                <li
                  key={task.key}
                  className={cn(
                    "rounded-lg border bg-card/70 p-3 space-y-2 transition-colors",
                    isHl ? "border-primary shadow-[0_0_0_2px_hsl(var(--primary)/0.2)]" : "border-border",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="shrink-0 text-[10px] font-mono text-muted-foreground">{idx + 1}.</span>
                    {/* ID */}
                    <div className="flex items-center gap-1 shrink-0">
                      <span className="text-[10px] text-muted-foreground">{t("plan.editor.task_id_label")}:</span>
                      <input
                        type="text"
                        disabled={isLocked}
                        value={task.id}
                        onChange={(e) => updateTask(task.key, { id: e.target.value })}
                        className={cn(
                          "w-24 rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[11px] focus:outline-none focus:ring-1 focus:ring-primary",
                          isLocked && "opacity-60 cursor-not-allowed",
                        )}
                      />
                    </div>
                    <div className="min-w-0 flex-1">
                      <input
                        type="text"
                        disabled={isLocked}
                        value={task.title}
                        onChange={(e) => updateTask(task.key, { title: e.target.value })}
                        placeholder={t("plan.editor.task_title_label")}
                        className={cn(
                          "w-full rounded border border-border bg-background px-2 py-0.5 text-[12px] font-medium focus:outline-none focus:ring-1 focus:ring-primary",
                          isLocked && "opacity-60 cursor-not-allowed",
                        )}
                      />
                    </div>
                    {!isLocked && (
                      <button
                        type="button"
                        onClick={() => removeTask(task.key)}
                        className="shrink-0 text-muted-foreground hover:text-destructive transition-colors"
                        title={t("plan.editor.remove_task")}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                  <textarea
                    disabled={isLocked}
                    value={task.description}
                    onChange={(e) => updateTask(task.key, { description: e.target.value })}
                    placeholder={t("plan.editor.task_desc_label")}
                    rows={1}
                    className={cn(
                      "w-full resize-none rounded border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-primary",
                      isLocked && "opacity-60 cursor-not-allowed",
                    )}
                  />
                  <div className="flex items-center gap-1.5">
                    <span className="shrink-0 text-[10px] text-muted-foreground">{t("plan.editor.task_deps_label")}:</span>
                    <input
                      type="text"
                      disabled={isLocked}
                      value={task.depsRaw}
                      onChange={(e) => updateTask(task.key, { depsRaw: e.target.value })}
                      placeholder={t("plan.editor.task_deps_placeholder")}
                      className={cn(
                        "min-w-0 flex-1 rounded border border-border bg-background px-2 py-0.5 font-mono text-[10px] focus:outline-none focus:ring-1 focus:ring-primary",
                        isLocked && "opacity-60 cursor-not-allowed",
                      )}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        </div>

        {/* markdown preview */}
        <div className="space-y-1.5">
          <button
            type="button"
            onClick={() => setShowMarkdown((v) => !v)}
            className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
          >
            {showMarkdown ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {showMarkdown ? t("plan.editor.preview_md") : t("plan.editor.export_md")}
          </button>
          {showMarkdown && exportedMarkdown && (
            <pre className="overflow-x-auto rounded-md border border-border bg-muted/40 p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
              {exportedMarkdown}
            </pre>
          )}
        </div>
      </div>

      {/* footer */}
      <div className="shrink-0 border-t border-border bg-card/80 px-4 py-3">
        {statusMsg && (
          <p className="mb-2 text-[11px] text-muted-foreground">{statusMsg}</p>
        )}

        {userDecision && (
          <p className="mb-2 text-[12px] font-medium">
            {userDecision === "approved"
              ? t("plan.decision.approved")
              : t("plan.decision.rejected")}
          </p>
        )}

        {showFooterActions && (
          <div className="flex gap-2">
            <button
              type="button"
              disabled={isSubmitting || !planId_}
              onClick={onApprove}
              className="flex flex-1 items-center justify-center gap-2 rounded-md bg-primary px-3 py-1.5 text-[12px] font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {isSubmitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              {t("plan.actions.approve")}
            </button>
            <button
              type="button"
              disabled={isSubmitting || !planId_}
              onClick={onReject}
              className="flex items-center justify-center rounded-md border border-destructive/60 px-3 py-1.5 text-[12px] font-medium text-destructive/90 transition-colors hover:bg-destructive/10 disabled:opacity-50"
            >
              {t("plan.actions.reject")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

"use client";

import { CheckCircle2, ChevronRight, Loader2, XCircle } from "lucide-react";
import type { PlanExecutionProgressState } from "@/hooks/use-plan-execution-progress";
import {
  countCompletedPlanTasks,
  planExecutionProgressPercent,
  resolveCurrentPlanTask,
} from "@/lib/plan-execution-view";
import { cn } from "@/lib/cn";

function statusIcon(status: string | undefined, running: boolean) {
  if (status === "done") {
    return <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500/90" />;
  }
  if (status === "error") {
    return <XCircle className="h-4 w-4 shrink-0 text-destructive" />;
  }
  if (running) {
    return <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />;
  }
  return <Loader2 className="h-4 w-4 shrink-0 text-muted-foreground/50" />;
}

export function PlanExecutionChatBanner({
  progress,
  onOpenTask,
  onOpenAllTasks,
}: {
  progress: PlanExecutionProgressState;
  onOpenTask?: (taskId: string) => void;
  onOpenAllTasks?: () => void;
}) {
  const tasks = progress.tasks || [];
  const doneCount = countCompletedPlanTasks(tasks);
  const total = tasks.length;
  const percent = planExecutionProgressPercent(tasks);
  const finished = progress.done || progress.status === "done";
  const failed = progress.status === "error";
  const cancelled = progress.status === "cancelled";
  const current = resolveCurrentPlanTask(tasks, progress.progress);
  const running =
    !finished &&
    !failed &&
    !cancelled &&
    (progress.progress?.phase === "task_start" || current?.status === "running");

  const headline = finished
    ? failed
      ? "Esecuzione piano non riuscita"
      : cancelled
        ? "Esecuzione piano annullata"
        : "Piano completato"
    : progress.label || "Esecuzione piano in corso…";

  const summaryLine = finished
    ? progress.error || progress.label || headline
    : current
      ? `${current.task_id}${current.title ? ` — ${current.title}` : ""}`
      : "In attesa della prossima task…";

  const clickable = !!current && typeof onOpenTask === "function" && !finished;

  return (
    <div className="mx-auto mb-4 w-full max-w-[min(92%,48rem)] rounded-2xl border border-border/60 bg-muted/30 px-4 py-3 shadow-sm">
      <div className="flex items-start gap-3">
        <div className="mt-0.5">
          {finished ? (
            failed ? (
              <XCircle className="h-4 w-4 shrink-0 text-destructive" />
            ) : (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
            )
          ) : (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-foreground">{headline}</div>
          {total > 0 ? (
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-[width] duration-300 ease-out"
                style={{ width: `${percent}%` }}
              />
            </div>
          ) : null}
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {total > 0 ? (
              <span>
                {doneCount}/{total} completate
              </span>
            ) : null}
            {typeof onOpenAllTasks === "function" ? (
              <button
                type="button"
                onClick={onOpenAllTasks}
                className="inline-flex items-center gap-0.5 font-medium text-primary hover:underline"
              >
                Vedi tutte le task
                <ChevronRight className="h-3 w-3" />
              </button>
            ) : null}
          </div>
        </div>
      </div>

      {(current || finished) && (
        <button
          type="button"
          disabled={!clickable}
          onClick={() => current && onOpenTask?.(current.task_id)}
          className={cn(
            "mt-3 flex w-full items-start gap-2 rounded-xl border border-border/50 bg-background/60 px-3 py-2.5 text-left transition-colors",
            clickable && "hover:border-primary/40 hover:bg-background",
            !clickable && "cursor-default",
          )}
        >
          {statusIcon(
            finished ? (failed ? "error" : "done") : current?.status,
            !!running,
          )}
          <span className="min-w-0 flex-1">
            <span className="block text-sm text-foreground">{summaryLine}</span>
            {finished && progress.progress?.deliverable_path ? (
              <span className="mt-1 block font-mono text-[11px] text-muted-foreground">
                {progress.progress.deliverable_path}
              </span>
            ) : null}
          </span>
          {clickable ? <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" /> : null}
        </button>
      )}
    </div>
  );
}

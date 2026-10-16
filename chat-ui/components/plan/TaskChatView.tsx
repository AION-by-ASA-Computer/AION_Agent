"use client";

import { useMemo } from "react";
import { ArrowLeft, CheckCircle2, Loader2, PauseCircle, Square } from "lucide-react";
import type { PlanExecutionProgressState } from "@/hooks/use-plan-execution-progress";
import type { PlanExecutionTask } from "@/lib/api/plan-execution";
import {
  activitiesForPlanTask,
  isMessageInPlanTask,
  isPlanTaskRunning,
  planTaskTurns,
  taskHasConversation,
} from "@/lib/plan-execution-view";
import { TaskActivityFeed } from "@/components/plan/TaskActivityFeed";
import { cn } from "@/lib/cn";

export type TaskChatViewMessage = {
  id: string;
  role: string;
  metadata?: { plan_id?: string; plan_task_id?: string };
};

export function TaskChatView({
  task,
  tasks,
  messages,
  progress,
  onBack,
  onOpenTask,
  onCancel,
  renderMessage,
}: {
  task: PlanExecutionTask;
  tasks: PlanExecutionTask[];
  messages: TaskChatViewMessage[];
  progress: PlanExecutionProgressState;
  onBack: () => void;
  onOpenTask: (taskId: string) => void;
  onCancel?: () => void;
  renderMessage: (message: TaskChatViewMessage, msgIdx: number) => React.ReactNode;
}) {
  const isRunning = isPlanTaskRunning(
    task,
    progress.progress,
    progress.status,
    progress.done,
  );

  const turns = planTaskTurns(task);
  const hasConversation = taskHasConversation(task, messages);
  const taskActivities = useMemo(
    () => activitiesForPlanTask(progress.activities, task.task_id),
    [progress.activities, task.task_id],
  );

  const messagesByTurn = useMemo(() => {
    return turns.map((turn) =>
      messages.filter(
        (m) =>
          m.id === turn.user_message_id ||
          m.id === turn.assistant_message_id ||
          isMessageInPlanTask(m, { ...task, user_message_id: turn.user_message_id, assistant_message_id: turn.assistant_message_id }),
      ),
    );
  }, [messages, task, turns]);

  const flatMessages = useMemo(() => {
    if (!hasConversation) return [];
    const out: Array<{ kind: "retry"; index: number } | { kind: "msg"; message: TaskChatViewMessage; idx: number }> = [];
    messagesByTurn.forEach((turnMsgs, turnIdx) => {
      if (turnIdx > 0) out.push({ kind: "retry", index: turnIdx + 1 });
      turnMsgs.forEach((message, idx) => {
        out.push({ kind: "msg", message, idx });
      });
    });
    if (!out.length) {
      messages
        .filter((m) => isMessageInPlanTask(m, task))
        .forEach((message, idx) => out.push({ kind: "msg", message, idx }));
    }
    return out;
  }, [hasConversation, messages, messagesByTurn, task]);

  const nextTask = useMemo(() => {
    const idx = tasks.findIndex((t) => t.task_id === task.task_id);
    if (idx < 0) return null;
    return tasks.slice(idx + 1).find((t) => t.status !== "done") ?? null;
  }, [task.task_id, tasks]);

  const doneCount = tasks.filter((t) => t.status === "done").length;
  const showTranscript = !isRunning && flatMessages.length > 0;
  const showActivityFeed = isRunning || (!showTranscript && taskActivities.length > 0);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background/50">
      {/* Sleek Top Header Bar */}
      <div className="sticky top-0 z-20 border-b border-black/[0.06] dark:border-white/[0.08] bg-background/85 px-4 py-3 backdrop-blur-xl">
        <div className="mx-auto flex w-full max-w-[min(92%,52rem)] items-center justify-between gap-3">
          {/* Back Button */}
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-1.5 rounded-full border border-black/[0.08] dark:border-white/[0.09] bg-card/80 px-3 py-1.5 text-xs font-semibold text-foreground shadow-2xs hover:bg-card hover:border-primary/40 transition-all active:scale-[0.98]"
          >
            <ArrowLeft className="size-3.5 text-muted-foreground" />
            <span>Torna alla chat</span>
          </button>

          {/* Center/Right Task Information */}
          <div className="flex items-center gap-2 min-w-0">
            <span className="rounded-md bg-orange-500/10 text-orange-600 dark:text-orange-400 font-mono text-xs font-bold px-2 py-0.5 shrink-0">
              {task.task_id}
            </span>
            <span className="truncate text-xs sm:text-sm font-semibold text-foreground">
              {task.title || "Task operativa"}
            </span>

            {/* Status Badge */}
            <span
              className={cn(
                "ml-1 inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider shrink-0",
                task.status === "done"
                  ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30"
                  : task.status === "error"
                  ? "bg-destructive/15 text-destructive border border-destructive/30"
                  : isRunning
                  ? "bg-orange-500/15 text-orange-600 dark:text-orange-400 border border-orange-500/30 animate-pulse"
                  : "bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30"
              )}
            >
              {task.status === "done" ? (
                <>
                  <CheckCircle2 size={12} className="text-emerald-500" />
                  Completata
                </>
              ) : task.status === "error" ? (
                "Errore"
              ) : isRunning ? (
                <>
                  <Loader2 size={12} className="animate-spin text-orange-500" />
                  In esecuzione
                </>
              ) : (
                <>
                  <PauseCircle size={12} className="text-amber-500" />
                  In pausa
                </>
              )}
            </span>
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto px-3 py-4 sm:px-6 custom-scrollbar">
        <div className="mx-auto w-full max-w-[min(92%,52rem)] space-y-4">
          {isRunning ? (
            <div>
              <h3 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                <span>Operazioni e Tool in Corso</span>
              </h3>
              <TaskActivityFeed activities={taskActivities} running={isRunning} />
            </div>
          ) : null}

          {!isRunning && !hasConversation ? (
            <div className="rounded-2xl border border-dashed border-border/70 bg-card/30 p-8 text-center text-sm text-muted-foreground">
              <span>Conversazione non disponibile per questa task.</span>
            </div>
          ) : null}

          {showTranscript ? (
            <div className="space-y-4">
              {flatMessages.map((item, i) => {
                if (item.kind === "retry") {
                  return (
                    <div
                      key={`retry-${item.index}`}
                      className="my-4 flex items-center gap-3 text-[0.786em] font-medium uppercase tracking-wide text-muted-foreground"
                    >
                      <span className="h-px flex-1 bg-border/60" />
                      Retry #{item.index}
                      <span className="h-px flex-1 bg-border/60" />
                    </div>
                  );
                }
                return (
                  <div key={`${item.message.id}-${i}`}>{renderMessage(item.message, item.idx)}</div>
                );
              })}
            </div>
          ) : null}

          {!isRunning && !showTranscript && showActivityFeed ? (
            <div>
              <h3 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                Riepilogo Operazioni Eseguite
              </h3>
              <TaskActivityFeed activities={taskActivities} running={false} />
            </div>
          ) : null}

          {task.status === "done" && nextTask ? (
            <button
              type="button"
              onClick={() => onOpenTask(nextTask.task_id)}
              className="mt-6 w-full flex items-center justify-between rounded-2xl border border-orange-500/30 bg-orange-500/5 hover:bg-orange-500/10 p-4 text-left transition-all shadow-2xs group"
            >
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-emerald-600 dark:text-emerald-400 block mb-0.5">
                  ✓ Task completata
                </span>
                <span className="text-sm font-semibold text-foreground">
                  Prosegui con <code className="font-mono text-xs bg-muted/60 px-1.5 py-0.5 rounded">{nextTask.task_id}</code>
                  {nextTask.title ? ` — ${nextTask.title}` : ""}
                </span>
              </div>
              <span className="text-xs font-semibold text-orange-600 dark:text-orange-400 group-hover:translate-x-1 transition-transform">
                Apri task →
              </span>
            </button>
          ) : null}
        </div>
      </div>

      {/* Footer Cancel Action (Running Mode) */}
      {isRunning && typeof onCancel === "function" ? (
        <div className="border-t border-black/[0.06] dark:border-white/[0.08] bg-background/85 px-4 py-2.5 backdrop-blur-md">
          <div className="mx-auto flex w-full max-w-[min(92%,52rem)] items-center justify-between gap-3 text-xs text-muted-foreground">
            <span className="font-medium">
              Task in esecuzione… ({doneCount}/{tasks.length || "?"} completate)
            </span>
            <button
              type="button"
              onClick={onCancel}
              className="inline-flex items-center gap-1.5 rounded-xl border border-destructive/30 px-3 py-1.5 text-xs font-semibold text-destructive hover:bg-destructive/10 transition-colors"
            >
              <Square className="size-3.5 fill-current" />
              Annulla esecuzione
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

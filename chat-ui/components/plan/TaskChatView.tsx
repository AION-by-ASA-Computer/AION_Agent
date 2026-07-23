"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Loader2, Square } from "lucide-react";
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

function taskStatusLabel(task: PlanExecutionTask, running: boolean): string {
  if (task.status === "done") return "Completata";
  if (task.status === "error") return "Errore";
  if (running || task.status === "running") return "In esecuzione";
  return "In attesa";
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

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
  const [startedAt] = useState(() => Date.now());
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!isRunning) return undefined;
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(t);
  }, [isRunning, startedAt]);

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
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="sticky top-0 z-10 border-b border-border/60 bg-background/95 px-4 py-3 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="mx-auto flex w-full max-w-[min(92%,48rem)] items-center gap-3">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-1 rounded-lg border border-border/60 px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Torna alla chat
          </button>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-foreground">
              <code className="font-mono text-xs text-muted-foreground">{task.task_id}</code>
              {task.title ? <span className="text-foreground"> — {task.title}</span> : null}
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[0.786em] text-muted-foreground">
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 font-medium",
                  task.status === "done" && "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
                  task.status === "error" && "bg-destructive/10 text-destructive",
                  isRunning && "bg-primary/10 text-primary",
                  !isRunning && task.status !== "done" && task.status !== "error" && "bg-muted text-muted-foreground",
                )}
              >
                {taskStatusLabel(task, !!isRunning)}
              </span>
              {isRunning ? <span>{formatElapsed(elapsed)}</span> : null}
              {isRunning ? (
                <span className="inline-flex items-center gap-1 text-primary">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  operazioni in corso
                </span>
              ) : null}
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-4">
        <div className="mx-auto w-full max-w-[min(92%,48rem)]">
          {isRunning ? (
            <div className="mb-4">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Operazioni
              </h3>
              <TaskActivityFeed activities={taskActivities} running={isRunning} />
            </div>
          ) : null}

          {!isRunning && !hasConversation ? (
            <div className="rounded-xl border border-dashed border-border/70 bg-muted/20 px-4 py-8 text-center text-sm text-muted-foreground">
              Conversazione non disponibile per questa task.
              <div className="mt-1 text-xs">I piani eseguiti prima dell&apos;aggiornamento non registrano gli id messaggio.</div>
            </div>
          ) : null}

          {showTranscript ? (
            <>
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
            </>
          ) : null}

          {!isRunning && !showTranscript && showActivityFeed ? (
            <TaskActivityFeed activities={taskActivities} running={false} />
          ) : null}

          {!isRunning && hasConversation && flatMessages.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border/70 bg-muted/20 px-4 py-8 text-center text-sm text-muted-foreground">
              Nessun messaggio ancora per questa task.
            </div>
          ) : null}

          {task.status === "done" && nextTask ? (
            <button
              type="button"
              onClick={() => onOpenTask(nextTask.task_id)}
              className="mt-6 w-full rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 text-left text-sm hover:bg-primary/10"
            >
              <span className="font-medium text-foreground">Task completata</span>
              <span className="mt-1 block text-muted-foreground">
                Apri <code className="font-mono text-xs">{nextTask.task_id}</code>
                {nextTask.title ? ` — ${nextTask.title}` : ""}
              </span>
            </button>
          ) : null}
        </div>
      </div>

      {isRunning && typeof onCancel === "function" ? (
        <div className="border-t border-border/60 bg-background/95 px-4 py-2.5">
          <div className="mx-auto flex w-full max-w-[min(92%,48rem)] items-center justify-between gap-3 text-xs text-muted-foreground">
            <span>
              Task in esecuzione… {doneCount}/{tasks.length || "?"}
            </span>
            <button
              type="button"
              onClick={onCancel}
              className="inline-flex items-center gap-1 rounded-lg border border-destructive/40 px-2.5 py-1 font-medium text-destructive hover:bg-destructive/10"
            >
              <Square className="h-3 w-3" />
              Annulla esecuzione
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

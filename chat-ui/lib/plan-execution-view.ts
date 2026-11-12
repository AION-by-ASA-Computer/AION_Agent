import type {
  PlanExecutionActivity,
  PlanExecutionProgress,
  PlanExecutionTask,
} from "@/lib/api/plan-execution";

export type PlanViewMessage = {
  id: string;
  role: string;
  metadata?: {
    plan_id?: string;
    plan_task_id?: string;
  };
};

export type PlanTaskTurn = {
  user_message_id?: string;
  assistant_message_id?: string;
};

/** All turns for a task (multi-retry aware; legacy single-pair fallback). */
export function planTaskTurns(task: PlanExecutionTask | null | undefined): PlanTaskTurn[] {
  if (!task) return [];
  if (task.turns?.length) return task.turns;
  const uid = (task.user_message_id || "").trim();
  const aid = (task.assistant_message_id || "").trim();
  if (!uid && !aid) return [];
  return [
    {
      user_message_id: uid || undefined,
      assistant_message_id: aid || undefined,
    },
  ];
}

/**
 * Rebuild a finished plan run's task list from history messages.
 *
 * Used by the chat when no plan run is adopted any more (the run ended, or the
 * page was reloaded afterwards): task turns are recognised by their
 * `metadata.plan_task_id`, in transcript order. Each internal trigger opens a
 * turn and the following assistant reply of the same task closes it, so
 * retries show up as separate turns, like the live run payload. Tasks are
 * reported as "done" and titled with their id (titles only live in the run).
 * When several plans ran in the chat, `planId` restricts to one of them.
 */
export function planTasksFromMessages(
  messages: PlanViewMessage[],
  planId?: string | null,
): PlanExecutionTask[] {
  const pid = (planId || "").trim();
  const byId = new Map<string, PlanExecutionTask>();
  for (const m of messages) {
    const tid = (m.metadata?.plan_task_id || "").trim();
    if (!tid) continue;
    if (pid && (m.metadata?.plan_id || "").trim() !== pid) continue;
    let task = byId.get(tid);
    if (!task) {
      task = { task_id: tid, title: tid, status: "done", turns: [] };
      byId.set(tid, task);
    }
    const turns = task.turns!;
    const last = turns[turns.length - 1];
    if (m.role === "internal" || m.role === "user") {
      turns.push({ user_message_id: m.id });
    } else if (m.role === "assistant") {
      if (last && !last.assistant_message_id) last.assistant_message_id = m.id;
      else turns.push({ assistant_message_id: m.id });
    }
  }
  return [...byId.values()];
}

/** Message IDs belonging to a plan execution task turn (internal trigger + assistant reply). */
export function messageIdsForPlanTask(task: PlanExecutionTask | null | undefined): Set<string> {
  const ids = new Set<string>();
  for (const turn of planTaskTurns(task)) {
    const uid = (turn.user_message_id || "").trim();
    const aid = (turn.assistant_message_id || "").trim();
    if (uid) ids.add(uid);
    if (aid) ids.add(aid);
  }
  return ids;
}

export function isMessageInPlanTask(
  message: PlanViewMessage,
  task: PlanExecutionTask | null | undefined,
): boolean {
  const tid = (task?.task_id || "").trim();
  const metaTid = (message.metadata?.plan_task_id || "").trim();
  if (tid && metaTid && tid === metaTid) return true;
  const ids = messageIdsForPlanTask(task);
  if (!ids.size) return false;
  return ids.has(message.id);
}

export function allPlanExecutionMessageIds(
  tasks: PlanExecutionTask[] | null | undefined,
): Set<string> {
  const ids = new Set<string>();
  for (const task of tasks || []) {
    for (const mid of messageIdsForPlanTask(task)) ids.add(mid);
  }
  return ids;
}

export function taskHasConversation(
  task: PlanExecutionTask | null | undefined,
  messages?: PlanViewMessage[],
): boolean {
  if (messageIdsForPlanTask(task).size > 0) return true;
  const tid = (task?.task_id || "").trim();
  if (!tid || !messages?.length) return false;
  return messages.some((m) => isMessageInPlanTask(m, task));
}

export function findPlanTask(
  tasks: PlanExecutionTask[] | null | undefined,
  taskId: string | null | undefined,
): PlanExecutionTask | null {
  const tid = (taskId || "").trim();
  if (!tid || !tasks?.length) return null;
  return tasks.find((t) => t.task_id === tid) ?? null;
}

export function resolveCurrentPlanTask(
  tasks: PlanExecutionTask[],
  progress: PlanExecutionProgress | null | undefined,
): PlanExecutionTask | null {
  const runningId =
    progress?.phase === "task_start" ? (progress.task_id || "").trim() : "";
  if (runningId) return findPlanTask(tasks, runningId);
  const running = tasks.find((t) => t.status === "running");
  if (running) return running;
  return (
    tasks.find((t) => t.status !== "done" && t.status !== "error") ?? null
  );
}

export function planExecutionProgressPercent(tasks: PlanExecutionTask[]): number {
  if (!tasks.length) return 0;
  const done = tasks.filter((t) => t.status === "done").length;
  return Math.round((done / tasks.length) * 100);
}

export function countCompletedPlanTasks(tasks: PlanExecutionTask[]): number {
  return tasks.filter((t) => t.status === "done").length;
}

export function activitiesForPlanTask(
  activities: PlanExecutionActivity[] | null | undefined,
  taskId: string,
): PlanExecutionActivity[] {
  const tid = (taskId || "").trim();
  if (!tid) return [];
  return (activities || []).filter((a) => {
    const at = (a.task_id || "").trim();
    return !at || at === tid;
  });
}

export function isPlanTaskRunning(
  task: PlanExecutionTask,
  progress: PlanExecutionProgress | null | undefined,
  runStatus?: string,
  runDone?: boolean,
): boolean {
  if (task.status === "running") return true;
  if (runDone || runStatus === "done" || runStatus === "error" || runStatus === "cancelled") {
    return false;
  }
  const tid = (task.task_id || "").trim();
  const progressTid = (progress?.task_id || "").trim();
  const livePhase =
    progress?.phase === "task_start" ||
    progress?.phase === "task_turn_started" ||
    progress?.phase === "tool";
  return livePhase && progressTid === tid;
}

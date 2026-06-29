"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchPlanExecutionStatus,
  subscribePlanExecutionStream,
  type PlanExecutionActivity,
  type PlanExecutionProgress,
  type PlanExecutionTask,
} from "@/lib/api/plan-execution";

export type PlanExecutionProgressState = {
  status: string;
  label: string;
  tasks: PlanExecutionTask[];
  activities: PlanExecutionActivity[];
  progress: PlanExecutionProgress | null;
  done: boolean;
  error: string | null;
};

type Listener = (state: PlanExecutionProgressState) => void;

type SharedRun = {
  state: PlanExecutionProgressState;
  listeners: Set<Listener>;
  unsub: (() => void) | null;
  refCount: number;
};

const sharedRuns = new Map<string, SharedRun>();

function emptyState(): PlanExecutionProgressState {
  return {
    status: "running",
    label: "",
    tasks: [],
    activities: [],
    progress: null,
    done: false,
    error: null,
  };
}

function statusToProgressEvent(st: Awaited<ReturnType<typeof fetchPlanExecutionStatus>>): PlanExecutionProgress | null {
  if (!st) return null;
  const progress = st.progress || {};
  return {
    ...progress,
    status: st.status,
    plan_id: st.plan_id,
    activities: st.activities,
    tasks: st.tasks,
    final: st.status !== "running",
  };
}

function applyEvent(prev: PlanExecutionProgressState, ev: PlanExecutionProgress): PlanExecutionProgressState {
  const label = ev.label || ev.message || prev.label;
  const status = ev.status || (ev.final ? "done" : ev.error ? "error" : prev.status);
  const activities =
    ev.activities?.length
      ? ev.activities
      : label && ev.phase !== "tool"
        ? [
            ...prev.activities,
            {
              label,
              message: ev.message,
              task_id: ev.task_id,
              phase: ev.phase,
              tool_name: ev.tool_name,
              status: ev.status,
              detail: ev.detail,
              ts: Date.now() / 1000,
            },
          ].slice(-100)
        : prev.activities;
  const tasks = ev.tasks?.length ? ev.tasks : prev.tasks;
  return {
    status,
    label,
    tasks,
    activities,
    progress: ev,
    done: !!ev.final || status === "done" || status === "error" || status === "cancelled",
    error: ev.error || (status === "error" ? label : null),
  };
}

function ensureSubscription(
  runId: string,
  userId: string,
  token: string | null | undefined,
  onTaskDone?: (taskId: string) => void,
  onTaskTurnStarted?: (ev: PlanExecutionProgress) => void,
): SharedRun {
  let shared = sharedRuns.get(runId);
  if (shared) return shared;

  shared = {
    state: emptyState(),
    listeners: new Set(),
    unsub: null,
    refCount: 0,
  };
  sharedRuns.set(runId, shared);

  const notify = () => {
    for (const fn of shared!.listeners) fn(shared!.state);
  };

  void fetchPlanExecutionStatus(runId, userId, token).then((st) => {
    const seed = statusToProgressEvent(st);
    if (!seed) return;
    shared!.state = applyEvent(shared!.state, seed);
    notify();
  });

  shared.unsub = subscribePlanExecutionStream(
    runId,
    userId,
    token,
    (ev) => {
      const prevPhase = shared!.state.progress?.phase;
      shared!.state = applyEvent(shared!.state, ev);
      notify();
      if (ev.phase === "task_turn_started") {
        onTaskTurnStarted?.(ev);
      }
      if (ev.phase === "task_done" && ev.task_id && prevPhase !== "task_done") {
        onTaskDone?.(String(ev.task_id));
      }
      if (ev.final) {
        shared!.state.done = true;
        notify();
      }
    },
    () => {
      shared!.state = { ...shared!.state, done: true };
      notify();
    },
  );

  return shared;
}

function releaseSubscription(runId: string) {
  const shared = sharedRuns.get(runId);
  if (!shared) return;
  shared.refCount -= 1;
  if (shared.refCount <= 0) {
    shared.unsub?.();
    sharedRuns.delete(runId);
  }
}

export type UsePlanExecutionProgressOptions = {
  onTaskDone?: (taskId: string) => void;
  onTaskTurnStarted?: (ev: PlanExecutionProgress) => void;
};

export function usePlanExecutionProgress(
  runId: string | null | undefined,
  userId: string,
  token?: string | null,
  options?: UsePlanExecutionProgressOptions,
): PlanExecutionProgressState | null {
  const [state, setState] = useState<PlanExecutionProgressState | null>(null);
  const onTaskDoneRef = useRef(options?.onTaskDone);
  onTaskDoneRef.current = options?.onTaskDone;
  const onTaskTurnStartedRef = useRef(options?.onTaskTurnStarted);
  onTaskTurnStartedRef.current = options?.onTaskTurnStarted;

  const listener = useCallback((next: PlanExecutionProgressState) => {
    setState({ ...next });
  }, []);

  useEffect(() => {
    const rid = (runId || "").trim();
    if (!rid || !userId) {
      setState(null);
      return undefined;
    }

    const shared = ensureSubscription(
      rid,
      userId,
      token,
      (taskId) => {
        onTaskDoneRef.current?.(taskId);
      },
      (ev) => {
        onTaskTurnStartedRef.current?.(ev);
      },
    );
    shared.refCount += 1;
    shared.listeners.add(listener);
    setState({ ...shared.state });

    return () => {
      shared.listeners.delete(listener);
      releaseSubscription(rid);
    };
  }, [runId, userId, token, listener]);

  return state;
}

import { apiBase } from "../config";
import { baseUserHeaders, jsonHeaders } from "./aion";

export type PlanExecutionActivity = {
  phase?: string;
  label?: string;
  message?: string;
  task_id?: string;
  title?: string;
  index?: number;
  total?: number;
  ts?: number;
  tool_name?: string;
  status?: string;
  detail?: string;
};

export type PlanExecutionTaskTurn = {
  user_message_id?: string;
  assistant_message_id?: string;
};

export type PlanExecutionTask = {
  task_id: string;
  title?: string;
  status?: string;
  user_message_id?: string;
  assistant_message_id?: string;
  /** One entry per attempt (retry); legacy runs use the single id pair only. */
  turns?: PlanExecutionTaskTurn[];
};

export type PlanExecutionProgress = {
  phase?: string;
  label?: string;
  message?: string;
  status?: string;
  final?: boolean;
  error?: string;
  summary?: string;
  deliverable_path?: string;
  plan_id?: string;
  tasks?: PlanExecutionTask[];
  activities?: PlanExecutionActivity[];
  index?: number;
  total?: number;
  task_id?: string;
  user_message_id?: string;
  assistant_message_id?: string;
  tool_name?: string;
  detail?: string;
};

export type PlanExecutionJob = {
  run_id: string;
  plan_id: string;
  status: string;
  progress?: PlanExecutionProgress;
  activities?: PlanExecutionActivity[];
  tasks?: PlanExecutionTask[];
  started_at?: number;
  chat_session_id?: string;
};

const WATCHED_PREFIX = "aion_plan_exec_watched_";

export type WatchedPlanExecution = { runId: string; planId: string; ts: number };

function watchedStorageKey(chatSessionId: string): string {
  return `${WATCHED_PREFIX}${chatSessionId || "default"}`;
}

export function loadWatchedPlanExecutions(chatSessionId: string): WatchedPlanExecution[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(watchedStorageKey(chatSessionId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as WatchedPlanExecution[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function rememberWatchedPlanExecution(
  runId: string,
  planId: string,
  chatSessionId: string
): void {
  if (typeof window === "undefined") return;
  const list = loadWatchedPlanExecutions(chatSessionId).filter((x) => x.runId !== runId);
  list.unshift({ runId, planId, ts: Date.now() });
  localStorage.setItem(watchedStorageKey(chatSessionId), JSON.stringify(list.slice(0, 20)));
}

export type PlanExecutionStatus = {
  status: string;
  plan_id: string;
  progress?: PlanExecutionProgress;
  activities?: PlanExecutionActivity[];
  tasks?: PlanExecutionTask[];
  started_at?: number;
  chat_session_id?: string;
};

export type PlanExecutionRunSummary = {
  run_id: string;
  plan_id: string;
  status: string;
  started_at?: number;
  completed_at?: number;
  chat_session_id?: string;
  tasks?: PlanExecutionTask[];
};

export async function fetchPlanExecutionStatus(
  runId: string,
  userId: string,
  token?: string | null,
): Promise<PlanExecutionStatus | null> {
  const r = await fetch(`${apiBase()}/plan-execution/status/${encodeURIComponent(runId)}`, {
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) return null;
  return r.json();
}

export async function fetchPlanExecutionRuns(
  userId: string,
  token?: string | null,
  chatSessionId?: string,
  limit = 20,
): Promise<PlanExecutionRunSummary[]> {
  const params = new URLSearchParams();
  if (chatSessionId) params.set("chat_session_id", chatSessionId);
  params.set("limit", String(limit));
  const r = await fetch(`${apiBase()}/plan-execution/runs?${params.toString()}`, {
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) return [];
  const j = (await r.json()) as { runs?: PlanExecutionRunSummary[] };
  return j.runs || [];
}

export async function fetchActivePlanExecutions(
  userId: string,
  token?: string | null,
  chatSessionId?: string
): Promise<PlanExecutionJob[]> {
  const params = new URLSearchParams();
  if (chatSessionId) params.set("chat_session_id", chatSessionId);
  const q = params.toString();
  const r = await fetch(`${apiBase()}/plan-execution/active${q ? `?${q}` : ""}`, {
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) return [];
  const j = (await r.json()) as { active?: PlanExecutionJob[] };
  return j.active || [];
}

export async function startPlanExecution(
  userId: string,
  body: { plan_id: string; chat_session_id?: string; profile_name?: string },
  token?: string | null
): Promise<{ run_id: string; status: string; plan_id: string }> {
  const r = await fetch(`${apiBase()}/plan-execution/start`, {
    method: "POST",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `HTTP ${r.status}`);
  }
  return r.json();
}

export async function cancelPlanExecution(
  runId: string,
  userId: string,
  token?: string | null
): Promise<void> {
  await fetch(`${apiBase()}/plan-execution/cancel/${encodeURIComponent(runId)}`, {
    method: "POST",
    headers: baseUserHeaders(userId, token),
  });
}

export async function fetchPlanExecutionResult(
  runId: string,
  userId: string,
  token?: string | null
): Promise<{ summary: string; plan_id: string; deliverable_path?: string } | null> {
  const r = await fetch(`${apiBase()}/plan-execution/result/${encodeURIComponent(runId)}`, {
    method: "POST",
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) return null;
  return r.json();
}

export function subscribePlanExecutionStream(
  runId: string,
  userId: string,
  token: string | null | undefined,
  onEvent: (data: PlanExecutionProgress) => void,
  onDone: () => void
): () => void {
  const headers = baseUserHeaders(userId, token);
  const params = new URLSearchParams();
  if (token) params.set("access_token", token);
  const qs = params.toString();
  const url = `${apiBase()}/plan-execution/stream/${encodeURIComponent(runId)}${qs ? `?${qs}` : ""}`;
  let closed = false;

  const start = async () => {
    try {
      const r = await fetch(url, { headers: { ...headers, Accept: "text/event-stream" } });
      if (!r.ok || !r.body) {
        onDone();
        return;
      }
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (!closed) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() || "";
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          try {
            const data = JSON.parse(line.slice(6)) as PlanExecutionProgress;
            onEvent(data);
            if (data.final) {
              onDone();
              return;
            }
          } catch {
            /* ignore */
          }
        }
      }
      onDone();
    } catch {
      if (!closed) onDone();
    }
  };

  void start();
  return () => {
    closed = true;
  };
}

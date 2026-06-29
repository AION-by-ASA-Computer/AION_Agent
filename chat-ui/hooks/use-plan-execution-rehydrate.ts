"use client";

import { useEffect, useRef } from "react";
import { fetchOrchestrationPlan, listSessionOrchestrationPlans } from "@/lib/api/aion";
import { apiBase } from "@/lib/config";
import {
  fetchActivePlanExecutions,
  fetchPlanExecutionRuns,
  fetchPlanExecutionStatus,
  loadWatchedPlanExecutions,
  type PlanExecutionRunSummary,
} from "@/lib/api/plan-execution";

export type PlanExecutionRehydrateResult = {
  runId: string | null;
  planId: string;
  status: string;
};

type Candidate = {
  runId: string;
  planId: string;
  status: string;
  startedAt: number;
  priority: number;
};

function statusPriority(status: string): number {
  if (status === "running") return 3;
  if (status === "done") return 2;
  if (status === "error" || status === "cancelled" || status === "interrupted") return 1;
  return 0;
}

async function pickBestRun(
  conversationId: string,
  userId: string,
  token: string | null | undefined,
): Promise<Candidate | null> {
  const [active, runs, watched] = await Promise.all([
    fetchActivePlanExecutions(userId, token, conversationId),
    fetchPlanExecutionRuns(userId, token, conversationId, 20),
    Promise.resolve(loadWatchedPlanExecutions(conversationId)),
  ]);

  const byRunId = new Map<string, Candidate>();

  const ingest = (runId: string, planId: string, status: string, startedAt = 0) => {
    const rid = runId.trim();
    const pid = planId.trim();
    if (!rid || !pid) return;
    const next: Candidate = {
      runId: rid,
      planId: pid,
      status: status || "running",
      startedAt: startedAt || 0,
      priority: statusPriority(status || "running"),
    };
    const cur = byRunId.get(rid);
    if (!cur || next.priority > cur.priority || next.startedAt > cur.startedAt) {
      byRunId.set(rid, next);
    }
  };

  for (const job of active) {
    ingest(job.run_id, job.plan_id, job.status || "running", job.started_at || 0);
  }

  for (const row of runs as PlanExecutionRunSummary[]) {
    ingest(row.run_id, row.plan_id, row.status, row.started_at || 0);
  }

  const statusFetches = watched.slice(0, 8).map(async (w) => {
    const st = await fetchPlanExecutionStatus(w.runId, userId, token);
    if (!st) return;
    ingest(
      w.runId,
      (st.plan_id || w.planId || "").trim(),
      st.status || "done",
      st.started_at || w.ts / 1000 || 0,
    );
  });
  await Promise.all(statusFetches);

  const candidates = [...byRunId.values()].sort((a, b) => {
    if (b.priority !== a.priority) return b.priority - a.priority;
    return b.startedAt - a.startedAt;
  });
  return candidates[0] ?? null;
}

export type UsePlanExecutionRehydrateOptions = {
  conversationId: string;
  userId: string;
  token?: string | null;
  enabled?: boolean;
  onAdopt: (runId: string, planId: string, opts?: { rehydrate?: boolean; status?: string }) => void;
  onRestorePlan: (planId: string, markdown: string, revision?: number) => void;
};

/**
 * On mount / conversation change: restore active or recent plan execution + orchestration plan markdown.
 */
export function usePlanExecutionRehydrate({
  conversationId,
  userId,
  token,
  enabled = true,
  onAdopt,
  onRestorePlan,
}: UsePlanExecutionRehydrateOptions): void {
  const onAdoptRef = useRef(onAdopt);
  const onRestoreRef = useRef(onRestorePlan);
  onAdoptRef.current = onAdopt;
  onRestoreRef.current = onRestorePlan;

  useEffect(() => {
    const cid = (conversationId || "").trim();
    if (!enabled || !cid || !userId) return undefined;

    let cancelled = false;

    const restorePlanMarkdown = async (planId: string) => {
      const plan = await fetchOrchestrationPlan(apiBase(), planId, cid, userId, token);
      if (cancelled || !plan) return;
      const md = String(plan.markdown || "").trim();
      if (md) {
        onRestoreRef.current(planId, md, plan.revision);
      }
    };

    void (async () => {
      try {
        const best = await pickBestRun(cid, userId, token);
        if (cancelled) return;

        if (best) {
          onAdoptRef.current(best.runId, best.planId, {
            rehydrate: true,
            status: best.status,
          });
          await restorePlanMarkdown(best.planId);
          return;
        }

        const plans = await listSessionOrchestrationPlans(apiBase(), cid, userId, token);
        if (cancelled || !plans.length) return;
        const approved =
          plans.find((p) => p.status === "approved") ??
          plans.find((p) => p.status === "draft_pending") ??
          plans[0];
        if (!approved?.plan_id) return;
        await restorePlanMarkdown(approved.plan_id);
      } catch {
        /* best-effort rehydrate */
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [conversationId, userId, token, enabled]);
}

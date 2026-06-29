"use client";

import dynamic from "next/dynamic";
import type { PlanExecutionProgressState } from "@/hooks/use-plan-execution-progress";
import { normalizePlanPendingChunk } from "@/lib/sse/planDisplay";
import type { ChatChunk } from "@/lib/sse/types";

const TaskPlanManagerV4 = dynamic(() => import("./TaskPlanManagerV4"), { ssr: false });

export function planChunkToProps(
  chunk: ChatChunk & { type: "orchestration_plan_pending" },
  apiBaseUrl: string,
  sessionId: string,
) {
  const normalized = normalizePlanPendingChunk(
    chunk as Parameters<typeof normalizePlanPendingChunk>[0],
  );
  return {
    apiBase: apiBaseUrl,
    planId: String(normalized.plan_id || ""),
    sessionId,
    initialPlan: normalized.plan || {},
    initialMarkdown: String(normalized.plan_markdown || ""),
    revision: Number(normalized.revision || 1),
    highlightTaskId: String(
      (chunk as { highlight_task_id?: string }).highlight_task_id ||
        (chunk as { highlightTaskId?: string }).highlightTaskId ||
        "",
    ),
  };
}

export function PlanDockPanel({
  chunk,
  apiBaseUrl,
  sessionId,
  remountKey,
  userId,
  profileName,
  authToken,
  executionRunId,
  executionProgress,
  selectedTaskId,
  onPlanApproved,
  onFinalSummary,
  onExecutionAdoptHandled,
  onTaskSelect,
}: {
  chunk: ChatChunk & { type: "orchestration_plan_pending" };
  apiBaseUrl: string;
  sessionId: string;
  remountKey: number;
  userId?: string;
  profileName?: string;
  authToken?: string | null;
  executionRunId?: string | null;
  executionProgress?: PlanExecutionProgressState | null;
  selectedTaskId?: string | null;
  onPlanApproved?: (runId: string, planId: string) => void;
  onFinalSummary?: (summary: string, planId: string, runId?: string) => void;
  onExecutionAdoptHandled?: () => void;
  onTaskSelect?: (taskId: string | null) => void;
}) {
  const props = planChunkToProps(chunk, apiBaseUrl, sessionId);

  return (
    <TaskPlanManagerV4
      key={remountKey}
      {...props}
      userId={userId}
      profileName={profileName}
      authToken={authToken}
      executionRunId={executionRunId || undefined}
      executionProgress={executionProgress || undefined}
      selectedTaskId={selectedTaskId || undefined}
      onPlanApproved={onPlanApproved}
      onFinalSummary={onFinalSummary}
      onExecutionAdoptHandled={onExecutionAdoptHandled}
      onTaskSelect={onTaskSelect}
    />
  );
}

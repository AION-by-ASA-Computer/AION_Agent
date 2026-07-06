"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ChatChunk } from "@/lib/sse/types";
import { PlanDockPanel } from "@/components/dock/PlanDockPanel";
import { StreamingContentPreview } from "@/components/dock/StreamingContentPreview";
import type { PlanExecutionProgressState } from "@/hooks/use-plan-execution-progress";

type PlanPanelPhase = "drafting" | "review" | "executing" | "done" | "error";

type PlanPendingChunk = ChatChunk & { type: "orchestration_plan_pending" };

function syntheticExecutionChunk(planId: string): PlanPendingChunk {
  return {
    type: "orchestration_plan_pending",
    plan_id: planId,
    plan: {},
    plan_markdown: "",
    todos: [],
    annotations: {},
    revision: 1,
    goal: "Execution plan",
  };
}

export function PlanPanel({
  chunk,
  apiBaseUrl,
  sessionId,
  remountKey,
  userId,
  profileName,
  token,
  planStreaming,
  planLiveMarkdown,
  adoptRunId,
  adoptPlanId,
  executionProgress,
  selectedTaskId,
  onAdoptHandled,
  onPlanApproved,
  onFinalSummary,
  onTaskSelect,
}: {
  chunk: PlanPendingChunk | null;
  apiBaseUrl: string;
  sessionId: string;
  remountKey: number;
  userId: string;
  profileName: string;
  token?: string | null;
  planStreaming?: boolean;
  planLiveMarkdown?: string;
  adoptRunId?: string | null;
  adoptPlanId?: string | null;
  executionProgress?: PlanExecutionProgressState | null;
  selectedTaskId?: string | null;
  onAdoptHandled?: () => void;
  onPlanApproved?: (runId: string, planId: string) => void;
  onFinalSummary?: (summary: string, planId: string, runId?: string) => void;
  onTaskSelect?: (taskId: string | null) => void;
}) {
  const [executionRunId, setExecutionRunId] = useState<string | null>(null);
  const [executionPlanId, setExecutionPlanId] = useState<string | null>(null);

  const handleApproved = useCallback(
    (runId: string, planId: string) => {
      setExecutionRunId(runId);
      setExecutionPlanId(planId);
      onPlanApproved?.(runId, planId);
    },
    [onPlanApproved],
  );

  useEffect(() => {
    if (!adoptRunId) {
      setExecutionRunId(null);
      setExecutionPlanId(null);
    }
  }, [adoptRunId]);

  const effectiveRunId = adoptRunId || executionRunId;
  const effectivePlanId = adoptPlanId || executionPlanId;
  const phase: PlanPanelPhase = useMemo(() => {
    if (effectiveRunId) return "executing";
    if (planStreaming) return "drafting";
    if (chunk) return "review";
    return "review";
  }, [chunk, effectiveRunId, planStreaming]);

  const effectiveChunk = useMemo((): PlanPendingChunk | null => {
    if (chunk) return chunk;
    const pid = (effectivePlanId || "").trim();
    if (pid && effectiveRunId) return syntheticExecutionChunk(pid);
    return null;
  }, [chunk, effectivePlanId, effectiveRunId]);

  if (planStreaming && chunk) {
    return (
      <StreamingContentPreview
        title={String(chunk.goal || chunk.plan_id || "Plan")}
        content={planLiveMarkdown || ""}
        streaming
        kind="plan"
      />
    );
  }

  if (!effectiveChunk) return null;

  return (
    <PlanDockPanel
      chunk={effectiveChunk}
      apiBaseUrl={apiBaseUrl}
      sessionId={sessionId}
      remountKey={remountKey}
      userId={userId}
      profileName={profileName}
      authToken={token}
      executionRunId={phase === "executing" ? effectiveRunId : null}
      executionProgress={executionProgress}
      selectedTaskId={selectedTaskId}
      onPlanApproved={handleApproved}
      onFinalSummary={onFinalSummary}
      onExecutionAdoptHandled={onAdoptHandled}
      onTaskSelect={onTaskSelect}
    />
  );
}

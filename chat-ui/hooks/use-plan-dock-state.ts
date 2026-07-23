"use client";

/**
 * Extracts plan-dock chunk state from ChatWorkspace.
 *
 * Manages:
 *   - planChunk / planMountKey state + ref
 *   - planStreamRevisionRef
 *   - openPlanDockFromChunk / openPlanDockFromMarkdown / updatePlanDockStreaming helpers
 *
 * The DB is the source of truth; localStorage snapshot is no longer used.
 */

import { useCallback, useRef, useState } from "react";
import {
  normalizePlanPendingChunk,
  planFromOrchestrationEvent,
  type OrchestrationPlanPendingEvent,
} from "@/lib/sse/planDisplay";
import type { ChatChunk } from "@/lib/sse/types";

type PlanPendingChunk = ChatChunk & { type: "orchestration_plan_pending" };

function chunkRevision(chunk: PlanPendingChunk | null): number {
  if (!chunk) return 0;
  const n = Number(chunk.revision || 1);
  return Number.isFinite(n) ? n : 1;
}

function planChunkFromMarkdown(
  planId: string,
  markdown: string,
  artifact?: Record<string, unknown>,
): PlanPendingChunk {
  return {
    type: "orchestration_plan_pending",
    plan_id: planId,
    plan: {},
    plan_markdown: markdown,
    todos: [],
    annotations: {},
    revision: 1,
    goal: String(artifact?.title || "Execution plan"),
    force_sidebar_refresh: true,
  };
}

export type UsePlanDockStateOptions = {
  /** Called when a new plan chunk triggers switching to the plan dock tab. */
  onOpenPlanTab: () => void;
};

export type UsePlanDockStateResult = {
  planChunk: PlanPendingChunk | null;
  planMountKey: number;
  planChunkRef: React.RefObject<PlanPendingChunk | null>;
  setPlanChunk: React.Dispatch<React.SetStateAction<PlanPendingChunk | null>>;
  openPlanDockFromChunk: (chunk: PlanPendingChunk) => void;
  openPlanDockFromMarkdown: (
    planId: string,
    markdown: string,
    artifact?: Record<string, unknown>,
  ) => void;
  updatePlanDockStreaming: (
    planId: string,
    markdown: string,
    artifact?: Record<string, unknown>,
  ) => void;
};

export function usePlanDockState({
  onOpenPlanTab,
}: UsePlanDockStateOptions): UsePlanDockStateResult {
  const [planChunk, setPlanChunk] = useState<PlanPendingChunk | null>(null);
  const [planMountKey, setPlanMountKey] = useState(0);

  const planChunkRef = useRef<PlanPendingChunk | null>(null);
  const planStreamRevisionRef = useRef(0);

  const openPlanDockFromChunk = useCallback(
    (chunk: PlanPendingChunk) => {
      const normalized =
        planFromOrchestrationEvent(
          chunk as unknown as OrchestrationPlanPendingEvent,
        )
          ? (normalizePlanPendingChunk(
            chunk as unknown as OrchestrationPlanPendingEvent &
            Record<string, unknown>,
          ) as PlanPendingChunk)
          : chunk;

      const planId = String(normalized.plan_id || "").trim();
      const current = planChunkRef.current;
      const samePlan = planId && String(current?.plan_id || "").trim() === planId;
      const incomingRevision = chunkRevision(normalized);

      if (
        samePlan &&
        !normalized.force_sidebar_refresh &&
        incomingRevision <= chunkRevision(current)
      ) {
        return;
      }

      planChunkRef.current = normalized;
      setPlanChunk(normalized);
      onOpenPlanTab();

      // Remount sidebar editor only when switching plans — not on every SSE refresh
      if (!samePlan) {
        setPlanMountKey((k) => k + 1);
      }
    },
    [onOpenPlanTab],
  );

  const openPlanDockFromMarkdown = useCallback(
    (planId: string, markdown: string, artifact?: Record<string, unknown>) => {
      const pid = planId.trim();
      const body = markdown.trim();
      if (!pid || !body) return;
      openPlanDockFromChunk(planChunkFromMarkdown(pid, body, artifact));
    },
    [openPlanDockFromChunk],
  );

  const updatePlanDockStreaming = useCallback(
    (planId: string, markdown: string, artifact?: Record<string, unknown>) => {
      const pid = planId.trim();
      if (!pid) return;
      planStreamRevisionRef.current += 1;
      openPlanDockFromChunk({
        type: "orchestration_plan_pending",
        plan_id: pid,
        plan: {},
        plan_markdown: markdown,
        todos: [],
        annotations: {},
        revision: planStreamRevisionRef.current,
        goal: String(artifact?.title || "Execution plan"),
        force_sidebar_refresh: true,
      });
    },
    [openPlanDockFromChunk],
  );

  return {
    planChunk,
    planMountKey,
    planChunkRef,
    setPlanChunk,
    openPlanDockFromChunk,
    openPlanDockFromMarkdown,
    updatePlanDockStreaming,
  };
}

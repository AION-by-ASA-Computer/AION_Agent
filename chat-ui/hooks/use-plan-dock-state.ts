"use client";

/**
 * Extracts plan-dock chunk state from ChatWorkspace.
 *
 * Manages:
 *   - planChunk / planMountKey state + ref
 *   - planStreamRevisionRef
 *   - openPlanDockFromChunk / openPlanDockFromMarkdown / updatePlanDockStreaming helpers
 *     (streaming updates are throttled to one per animation frame, see below)
 *
 * The DB is the source of truth; localStorage snapshot is no longer used.
 */

import { useCallback, useEffect, useRef, useState } from "react";
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
  // Streaming updates are coalesced to one per animation frame: the stream can
  // emit a plan update per token, and pushing each one through React (plus the
  // dock re-render it triggers via the shell layout effect) exceeded React's
  // nested-update limit ("Maximum update depth exceeded", React error #185).
  const streamFrameRef = useRef<number | null>(null);
  const pendingStreamRef = useRef<{
    planId: string;
    markdown: string;
    artifact?: Record<string, unknown>;
  } | null>(null);
  // Last streamed (planId, markdown) actually applied, to skip no-op updates.
  const lastStreamedRef = useRef<{ planId: string; markdown: string } | null>(null);

  /** Drop any streaming update still waiting for the next animation frame. */
  const cancelPendingStream = useCallback(() => {
    if (streamFrameRef.current !== null) {
      cancelAnimationFrame(streamFrameRef.current);
      streamFrameRef.current = null;
    }
    pendingStreamRef.current = null;
  }, []);

  // Never let a queued frame fire after the workspace unmounts.
  useEffect(() => cancelPendingStream, [cancelPendingStream]);

  /** Apply a plan chunk to the dock state (no throttling, no cancellation). */
  const applyPlanChunk = useCallback(
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

  /**
   * Open/refresh the plan dock with a definitive chunk (server `orchestration_plan_pending`,
   * history restore, final artifact). Cancels any queued streaming frame first, so a
   * stale "streaming-plan" preview can never overwrite the real plan afterwards.
   */
  const openPlanDockFromChunk = useCallback(
    (chunk: PlanPendingChunk) => {
      cancelPendingStream();
      lastStreamedRef.current = null;
      applyPlanChunk(chunk);
    },
    [applyPlanChunk, cancelPendingStream],
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

  /**
   * Live preview of a plan being generated. Called by ChatWorkspace for every
   * plan-related stream chunk (tokens included); only the latest value is kept
   * and applied once per animation frame, and identical markdown is skipped.
   */
  const updatePlanDockStreaming = useCallback(
    (planId: string, markdown: string, artifact?: Record<string, unknown>) => {
      const pid = planId.trim();
      if (!pid) return;
      pendingStreamRef.current = { planId: pid, markdown, artifact };
      if (streamFrameRef.current !== null) return;
      streamFrameRef.current = requestAnimationFrame(() => {
        streamFrameRef.current = null;
        const pending = pendingStreamRef.current;
        pendingStreamRef.current = null;
        if (!pending) return;
        const last = lastStreamedRef.current;
        if (last && last.planId === pending.planId && last.markdown === pending.markdown) {
          return;
        }
        lastStreamedRef.current = { planId: pending.planId, markdown: pending.markdown };
        planStreamRevisionRef.current += 1;
        applyPlanChunk({
          type: "orchestration_plan_pending",
          plan_id: pending.planId,
          plan: {},
          plan_markdown: pending.markdown,
          todos: [],
          annotations: {},
          revision: planStreamRevisionRef.current,
          goal: String(pending.artifact?.title || "Execution plan"),
          force_sidebar_refresh: true,
        });
      });
    },
    [applyPlanChunk],
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

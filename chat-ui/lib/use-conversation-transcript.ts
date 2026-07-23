"use client";

import { useCallback, useRef, type MutableRefObject } from "react";

import type { ConversationHistoryResult } from "@/lib/api/aion";
import { logHistoryFetch } from "@/lib/chat-debug";
import { mergeChatHistory, type MergeableChatMessage } from "@/lib/merge-chat-history";

export type TranscriptStreamingState = {
  streamingRef: MutableRefObject<boolean>;
  streamingConversationIdRef: MutableRefObject<string | null>;
};

export type HistoryApplyMode = "replace" | "merge";

/**
 * Transcript contract (client):
 * - Sidebar load / recovery finish → replace transcript (no cross-conversation merge).
 * - Post-stream / recovery poll / plan execution → merge only for the active conversation.
 */
function shouldSkipHistoryMerge(
  targetConversationId: string,
  streaming: TranscriptStreamingState,
): boolean {
  return (
    streaming.streamingRef.current &&
    streaming.streamingConversationIdRef.current === targetConversationId
  );
}

export function applyHistoryToMessages<T extends MergeableChatMessage>(
  prev: T[],
  mapped: T[],
  result: ConversationHistoryResult,
  targetConversationId: string,
  streaming: TranscriptStreamingState,
  opts?: { loadEpoch?: number; source?: string; mode?: HistoryApplyMode },
): { next: T[]; error: string | null } {
  logHistoryFetch(targetConversationId, {
    ok: result.ok,
    status: result.ok ? 200 : result.status,
    count: mapped.length,
    streamingRef: streaming.streamingRef.current,
    streamingConversationId: streaming.streamingConversationIdRef.current,
    loadEpoch: opts?.loadEpoch,
    source: opts?.source,
  });

  if (!result.ok) {
    const benignNewChat =
      result.status === 404 &&
      /conversation not found/i.test(result.error || "");
    if (benignNewChat) {
      return { next: prev, error: null };
    }
    return { next: prev, error: result.error };
  }

  if (shouldSkipHistoryMerge(targetConversationId, streaming)) {
    return { next: prev, error: null };
  }

  const mode = opts?.mode ?? "merge";
  if (mode === "replace") {
    return { next: mapped, error: null };
  }

  return {
    next: mergeChatHistory(prev, mapped, targetConversationId),
    error: null,
  };
}

/** Epoch + streaming conversation tracking for transcript loads. */
export function useConversationTranscriptRefs() {
  const historyLoadEpochRef = useRef(0);
  const streamingConversationIdRef = useRef<string | null>(null);
  const previousConversationIdRef = useRef<string | null>(null);

  const bumpHistoryLoadEpoch = useCallback(() => {
    historyLoadEpochRef.current += 1;
    return historyLoadEpochRef.current;
  }, []);

  const markStreamConversation = useCallback((conversationId: string | null) => {
    streamingConversationIdRef.current = conversationId;
  }, []);

  return {
    historyLoadEpochRef,
    streamingConversationIdRef,
    previousConversationIdRef,
    bumpHistoryLoadEpoch,
    markStreamConversation,
  };
}

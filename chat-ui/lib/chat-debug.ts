import { AION_CHAT_STREAM_DEBUG_ENABLED } from "@/lib/dev-flags";

/** Dev-only stream diagnostics (browser console). */
function isChatUiStreamDebug(): boolean {
  return AION_CHAT_STREAM_DEBUG_ENABLED;
}

/** Structured log for history load / sidebar re-entry debugging. */
export function logHistoryFetch(
  conversationId: string,
  payload: {
    ok: boolean;
    status?: number;
    count: number;
    streamingRef: boolean;
    streamingConversationId?: string | null;
    loadEpoch?: number;
    source?: string;
  },
): void {
  if (!isChatUiStreamDebug()) return;
  console.info("[aion-chat-ui] history fetch", {
    conversationId: conversationId.slice(0, 12),
    ...payload,
  });
}

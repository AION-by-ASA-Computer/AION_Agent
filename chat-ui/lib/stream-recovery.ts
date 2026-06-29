const PREFIX = "aion-active-stream:";

export type ActiveStreamMarker = {
  assistantMessageId: string;
  userMessageId: string;
  startedAt: number;
};

export function activeStreamMarkerKey(conversationId: string): string {
  return `${PREFIX}${conversationId}`;
}

export function writeActiveStreamMarker(
  conversationId: string,
  ids: { assistantMessageId: string; userMessageId: string },
): void {
  try {
    sessionStorage.setItem(
      activeStreamMarkerKey(conversationId),
      JSON.stringify({ ...ids, startedAt: Date.now() } satisfies ActiveStreamMarker),
    );
  } catch {
    /* quota / private mode */
  }
}

export function readActiveStreamMarker(conversationId: string): ActiveStreamMarker | null {
  try {
    const raw = sessionStorage.getItem(activeStreamMarkerKey(conversationId));
    if (!raw) return null;
    const data = JSON.parse(raw) as Partial<ActiveStreamMarker>;
    if (!data?.assistantMessageId || !data?.userMessageId) return null;
    return {
      assistantMessageId: String(data.assistantMessageId),
      userMessageId: String(data.userMessageId),
      startedAt: Number(data.startedAt) || Date.now(),
    };
  } catch {
    return null;
  }
}

export function clearActiveStreamMarker(conversationId: string): void {
  try {
    sessionStorage.removeItem(activeStreamMarkerKey(conversationId));
  } catch {
    /* ignore */
  }
}

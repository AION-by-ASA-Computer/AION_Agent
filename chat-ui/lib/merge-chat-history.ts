/** Minimal shape for transcript merge (matches ChatWorkspace ChatMessage). */
export type MergeableChatMessage = {
  id: string;
  content: string;
  reasoning?: string;
  segments?: unknown[];
  steps?: unknown[];
  artifacts?: unknown[];
  webSources?: unknown[];
  reasoningUnavailable?: boolean;
  role?: string;
  metadata?: {
    plan_id?: string;
    plan_task_id?: string;
  };
};

function textLen(m: MergeableChatMessage): number {
  return (m.content || "").trim().length;
}

/** Prefer the variant with more visible assistant/user payload (streaming vs stale DB). */
export function preferRicherMessage<T extends MergeableChatMessage>(local: T, server: T): T {
  const localText = textLen(local);
  const serverText = textLen(server);
  if (serverText > 0 && localText === 0) {
    return server;
  }

  const localRicher =
    localText > serverText ||
    (local.segments?.length ?? 0) > (server.segments?.length ?? 0) ||
    (local.steps?.length ?? 0) > (server.steps?.length ?? 0) ||
    (local.artifacts?.length ?? 0) > (server.artifacts?.length ?? 0);

  if (!localRicher) return server;

  return {
    ...server,
    content: local.content || server.content,
    reasoning: local.reasoning ?? server.reasoning,
    steps: local.steps?.length ? local.steps : server.steps,
    artifacts: local.artifacts?.length ? local.artifacts : server.artifacts,
    segments: local.segments?.length ? local.segments : server.segments,
    webSources: local.webSources?.length ? local.webSources : server.webSources,
    reasoningUnavailable: local.reasoningUnavailable ?? server.reasoningUnavailable,
    metadata: local.metadata ?? server.metadata,
  };
}

/**
 * Merge server history with local optimistic/streaming messages for the same conversation.
 * Never appends local-only rows when conversationId is set (guards cross-conversation pollution).
 */
export function mergeChatHistory<T extends MergeableChatMessage>(
  local: T[],
  server: T[],
  conversationId?: string,
): T[] {
  if (server.length === 0) return local;
  if (local.length === 0) return server;

  const serverById = new Map(server.map((m) => [m.id, m]));
  const merged: T[] = server.map((sm) => {
    const loc = local.find((m) => m.id === sm.id);
    return loc ? preferRicherMessage(loc, sm) : sm;
  });

  if (conversationId) {
    return merged;
  }

  for (const m of local) {
    if (!serverById.has(m.id)) merged.push(m);
  }
  return merged;
}

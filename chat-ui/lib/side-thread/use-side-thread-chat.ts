"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  chatStop,
  consumeChatStream,
  fetchConversationHistory,
  fetchStreamStatus,
  getChatStreamReconnect,
  postChatStream,
  saveChatMessage,
  type ChatHistoryMessage,
} from "@/lib/api/aion";
import { newTurn, reduceChunk, segmentsForMessage } from "@/lib/sse/reducer";
import type { TurnSegment, TurnState } from "@/lib/sse/types";
import { randomUUID } from "@/lib/uuid";

export type SideThreadMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  segments?: TurnSegment[];
};

export type SideThreadChatSettings = {
  profile: string;
  reasoningEffort?: string;
  thinkingEnabled?: boolean;
  llmProviderName?: string;
  toolsView?: "compact" | "hidden" | "partial" | "full";
  runtime?: Record<string, unknown>;
};

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

function fromHistory(rows: ChatHistoryMessage[]): SideThreadMessage[] {
  const out: SideThreadMessage[] = [];
  for (const h of rows) {
    if (h.role !== "user" && h.role !== "assistant") continue;
    if (h.role === "assistant") {
      out.push({
        id: h.id,
        role: "assistant",
        content: h.content || "",
        segments: segmentsForMessage({
          timeline: h.timeline ?? undefined,
          reasoning: h.reasoning,
          content: h.content,
          steps: h.steps?.map((s) => ({
            id: s.id,
            name: s.name,
            input: s.input,
            output: s.output,
            is_error: s.is_error,
          })),
        }),
      });
    } else {
      out.push({ id: h.id, role: "user", content: h.content || "" });
    }
  }
  return out;
}

/**
 * Minimal streaming chat engine for one side thread. It is independent from the main
 * ChatWorkspace engine: own messages, own AbortController, no shell side effects, so the
 * thread can stream while the parent conversation streams too (different session ids).
 *
 * `threadId === null` is the draft state: nothing exists server-side until the first send,
 * when `ensureThread()` creates the conversation and returns its id.
 */
export function useSideThreadChat(opts: {
  threadId: string | null;
  userId: string;
  token?: string | null;
  settings: SideThreadChatSettings;
  ensureThread: () => Promise<string>;
  onTurnFinished?: (threadId: string) => void;
}) {
  const { threadId, userId, token } = opts;
  const [messages, setMessages] = useState<SideThreadMessage[]>([]);
  const [turn, setTurn] = useState<TurnState | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [failedInput, setFailedInput] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const activeIdRef = useRef<string | null>(threadId);
  /** Id adopted locally right after creation: skip the history reload for it. */
  const adoptedIdRef = useRef<string | null>(null);
  const settingsRef = useRef(opts.settings);
  const ensureRef = useRef(opts.ensureThread);
  const finishedRef = useRef(opts.onTurnFinished);
  useEffect(() => {
    settingsRef.current = opts.settings;
    ensureRef.current = opts.ensureThread;
    finishedRef.current = opts.onTurnFinished;
  });

  const reloadHistory = useCallback(
    async (id: string, signal?: AbortSignal) => {
      const res = await fetchConversationHistory(id, userId, token, signal, { includeArchived: true });
      if (signal?.aborted || activeIdRef.current !== id) return false;
      if (!res.ok) {
        setError(res.error);
        return false;
      }
      setMessages(fromHistory(res.messages));
      return true;
    },
    [userId, token],
  );

  const consume = useCallback(
    async (id: string, stream: ReadableStream<Uint8Array> | null, onStarted?: (asstId: string) => void) => {
      let state = newTurn();
      setTurn(state);
      await consumeChatStream(stream, (chunk) => {
        if (activeIdRef.current !== id) return;
        if (chunk.type === "turn_started") {
          onStarted?.(String(chunk.assistant_message_id || ""));
          return;
        }
        state = reduceChunk(state, chunk);
        setTurn({ ...state });
      });
      return state;
    },
    [],
  );

  // Load history (and resume a running stream) whenever the open thread changes.
  useEffect(() => {
    // The draft just became this thread inside send(): keep the in-flight stream.
    if (threadId && adoptedIdRef.current === threadId) {
      adoptedIdRef.current = null;
      return;
    }
    activeIdRef.current = threadId;
    abortRef.current?.abort();
    abortRef.current = null;
    // Switching thread resets the local transcript before the server one arrives.
    /* eslint-disable react-hooks/set-state-in-effect */
    setTurn(null);
    setStreaming(false);
    setError(null);
    setFailedInput(null);
    if (!threadId) {
      setMessages([]);
      setLoading(false);
      return;
    }
    const ac = new AbortController();
    abortRef.current = ac;
    setMessages([]);
    setLoading(true);
    /* eslint-enable react-hooks/set-state-in-effect */
    void (async () => {
      const ok = await reloadHistory(threadId, ac.signal);
      if (ac.signal.aborted) return;
      setLoading(false);
      if (!ok) return;
      const st = await fetchStreamStatus(threadId, userId, token, ac.signal).catch(() => ({ active: false }));
      if (!st.active || ac.signal.aborted) return;
      setStreaming(true);
      try {
        const stream = await getChatStreamReconnect(threadId, userId, token, ac.signal);
        await consume(threadId, stream, (asstId) => {
          if (asstId) setMessages((prev) => prev.filter((m) => m.id !== asstId));
        });
      } catch (err) {
        if (!isAbort(err)) console.error("[side-thread] reconnect:", err);
      }
      if (ac.signal.aborted || activeIdRef.current !== threadId) return;
      await reloadHistory(threadId);
      setTurn(null);
      setStreaming(false);
    })();
    return () => ac.abort();
  }, [threadId, userId, token, reloadHistory, consume]);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || streaming) return;
      setError(null);
      setFailedInput(null);
      setStreaming(true);
      const userMsgId = randomUUID();
      const asstId = randomUUID();
      setMessages((prev) => [...prev, { id: userMsgId, role: "user", content: message }]);

      let id = activeIdRef.current;
      try {
        if (!id) {
          id = await ensureRef.current();
          adoptedIdRef.current = id;
          activeIdRef.current = id;
        }
      } catch (err) {
        setMessages((prev) => prev.filter((m) => m.id !== userMsgId));
        setStreaming(false);
        setError(err instanceof Error ? err.message : String(err));
        setFailedInput(message);
        return;
      }

      const convId = id;
      void saveChatMessage(convId, userMsgId, "user", message, userId, token).catch(() => undefined);
      const ac = new AbortController();
      abortRef.current = ac;
      const s = settingsRef.current;
      let finalAsstId = asstId;
      try {
        const stream = await postChatStream(
          {
            message,
            session_id: convId,
            profile: s.profile,
            user_id: userId,
            reasoning_effort: s.reasoningEffort,
            thinking_enabled: s.thinkingEnabled,
            agent_mode: "normal",
            plan_mode: false,
            deep_research_mode: false,
            user_message_id: userMsgId,
            assistant_message_id: asstId,
            message_source: "user_input",
            tools_view: s.toolsView,
            compact_mode: s.toolsView === "compact",
            llm_provider_name: s.llmProviderName || undefined,
            runtime: s.runtime,
          },
          token,
          ac.signal,
        );
        const state = await consume(convId, stream, (a) => {
          if (a) finalAsstId = a;
        });
        if (activeIdRef.current !== convId) return;
        const content = state.assistantContent;
        setMessages((prev) => [
          ...prev,
          { id: finalAsstId, role: "assistant", content, segments: state.segments },
        ]);
        setTurn(null);
        if (state.error && !content.trim()) {
          setError(state.error);
        }
        await reloadHistory(convId);
        finishedRef.current?.(convId);
      } catch (err) {
        if (isAbort(err)) {
          if (activeIdRef.current === convId) {
            setTurn(null);
            await reloadHistory(convId);
          }
        } else if (activeIdRef.current === convId) {
          setTurn(null);
          setError(err instanceof Error ? err.message : String(err));
          setFailedInput(message);
        }
      } finally {
        if (activeIdRef.current === convId) setStreaming(false);
        if (abortRef.current === ac) abortRef.current = null;
      }
    },
    [streaming, userId, token, consume, reloadHistory],
  );

  const stop = useCallback(async () => {
    const id = activeIdRef.current;
    abortRef.current?.abort();
    if (id) await chatStop(id, userId, token).catch(() => undefined);
  }, [userId, token]);

  const dismissError = useCallback(() => {
    setError(null);
    setFailedInput(null);
  }, []);

  return { messages, turn, streaming, loading, error, failedInput, send, stop, dismissError };
}

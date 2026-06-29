import { apiBase } from "../config";
import { researchError, researchLog, researchWarn } from "../research-debug";
import { baseUserHeaders, jsonHeaders } from "./aion";

export type ResearchActivity = {
  phase?: string;
  label?: string;
  message?: string;
  round?: number;
  queries?: number;
  total_sources?: number;
  total_findings?: number;
  query_preview?: string;
  url?: string;
  title?: string;
  ts?: number;
};

export type ResearchProgress = {
  phase?: string;
  round?: number;
  max_rounds?: number;
  queries?: number;
  total_sources?: number;
  total_findings?: number;
  message?: string;
  label?: string;
  status?: string;
  final?: boolean;
  error?: string;
  ts?: number;
  activities?: ResearchActivity[];
};

export type ResearchJob = {
  session_id: string;
  query: string;
  status: string;
  progress?: ResearchProgress;
  activities?: ResearchActivity[];
  started_at?: number;
  chat_session_id?: string;
};

export type ResearchLibraryItem = {
  id: string;
  query: string;
  category?: string;
  source_count?: number;
  status?: string;
  duration?: number;
  started_at?: number;
  completed_at?: number;
  archived?: boolean;
};

export function reportUrl(sessionId: string): string {
  return `${apiBase()}/research/report/${encodeURIComponent(sessionId)}`;
}

export async function startResearch(
  userId: string,
  body: {
    query: string;
    max_rounds?: number;
    max_time?: number;
    category?: string;
    chat_session_id?: string;
  },
  token?: string | null
): Promise<{ session_id: string; status: string; query: string }> {
  const r = await fetch(`${apiBase()}/research/start`, {
    method: "POST",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `HTTP ${r.status}`);
  }
  return r.json();
}

export type ResearchStatusResponse = {
  status: string;
  query?: string;
  progress?: ResearchProgress;
  activities?: ResearchActivity[];
  started_at?: number;
};

export async function fetchResearchStatus(
  sessionId: string,
  userId: string,
  token?: string | null
): Promise<ResearchStatusResponse | null> {
  const r = await fetch(`${apiBase()}/research/status/${encodeURIComponent(sessionId)}`, {
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    researchWarn("GET /research/status failed", { sessionId, status: r.status, body: body.slice(0, 200) });
    return null;
  }
  const data = (await r.json()) as ResearchStatusResponse;
  researchLog("status", { sessionId, status: data?.status, phase: data?.progress?.phase });
  return data;
}

const WATCHED_PREFIX = "aion_research_watched_";

export type WatchedResearch = { id: string; query: string; ts: number };

function watchedStorageKey(chatSessionId: string): string {
  return `${WATCHED_PREFIX}${chatSessionId || "default"}`;
}

export function loadWatchedResearch(chatSessionId: string): WatchedResearch[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(watchedStorageKey(chatSessionId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as WatchedResearch[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function rememberWatchedResearch(
  id: string,
  query: string,
  chatSessionId: string
): void {
  if (typeof window === "undefined") return;
  const list = loadWatchedResearch(chatSessionId).filter((x) => x.id !== id);
  list.unshift({ id, query, ts: Date.now() });
  localStorage.setItem(
    watchedStorageKey(chatSessionId),
    JSON.stringify(list.slice(0, 30))
  );
}

export async function fetchActiveResearch(
  userId: string,
  token?: string | null,
  chatSessionId?: string
): Promise<ResearchJob[]> {
  const params = new URLSearchParams();
  if (chatSessionId) params.set("chat_session_id", chatSessionId);
  const q = params.toString();
  const r = await fetch(`${apiBase()}/research/active${q ? `?${q}` : ""}`, {
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) {
    researchWarn("GET /research/active failed", { status: r.status, userId });
    return [];
  }
  const j = (await r.json()) as { active?: ResearchJob[] };
  const active = j.active || [];
  researchLog("active jobs", { count: active.length, ids: active.map((a) => a.session_id) });
  return active;
}

export async function fetchResearchLibrary(
  userId: string,
  token?: string | null,
  opts?: { search?: string; limit?: number; chatSessionId?: string }
): Promise<ResearchLibraryItem[]> {
  const params = new URLSearchParams();
  if (opts?.search) params.set("search", opts.search);
  if (opts?.limit) params.set("limit", String(opts.limit));
  if (opts?.chatSessionId) params.set("chat_session_id", opts.chatSessionId);
  const q = params.toString();
  const r = await fetch(`${apiBase()}/research/library${q ? `?${q}` : ""}`, {
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) {
    researchWarn("GET /research/library failed", { status: r.status });
    return [];
  }
  const j = (await r.json()) as { research?: ResearchLibraryItem[] };
  return j.research || [];
}

export async function cancelResearch(
  sessionId: string,
  userId: string,
  token?: string | null
): Promise<void> {
  await fetch(`${apiBase()}/research/cancel/${encodeURIComponent(sessionId)}`, {
    method: "POST",
    headers: baseUserHeaders(userId, token),
  });
}

export async function deleteResearch(
  sessionId: string,
  userId: string,
  token?: string | null
): Promise<void> {
  await fetch(`${apiBase()}/research/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    headers: baseUserHeaders(userId, token),
  });
}

export function subscribeResearchStream(
  sessionId: string,
  userId: string,
  token: string | null | undefined,
  onEvent: (data: ResearchProgress) => void,
  onDone: () => void
): () => void {
  const headers = baseUserHeaders(userId, token);
  const params = new URLSearchParams();
  if (token) params.set("access_token", token);
  const qs = params.toString();
  const url = `${apiBase()}/research/stream/${encodeURIComponent(sessionId)}${qs ? `?${qs}` : ""}`;
  let closed = false;

  const start = async () => {
    researchLog("SSE stream connect", { sessionId, url });
    try {
      const r = await fetch(url, { headers: { ...headers, Accept: "text/event-stream" } });
      if (!r.ok || !r.body) {
        researchWarn("SSE stream failed", { sessionId, status: r.status, ok: r.ok });
        onDone();
        return;
      }
      researchLog("SSE stream open", { sessionId });
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (!closed) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() || "";
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          try {
            const data = JSON.parse(line.slice(6)) as ResearchProgress;
            researchLog("SSE event", {
              sessionId,
              phase: data.phase,
              label: data.label,
              status: data.status,
              final: data.final,
            });
            onEvent(data);
            if (data.final) {
              researchLog("SSE stream done", { sessionId, status: data.status });
              onDone();
              return;
            }
          } catch {
            /* ignore */
          }
        }
      }
      researchLog("SSE stream closed", { sessionId });
      onDone();
    } catch (err) {
      researchError("SSE stream error", { sessionId, err });
      if (!closed) onDone();
    }
  };

  void start();
  return () => {
    researchLog("SSE stream unsubscribe", { sessionId });
    closed = true;
  };
}

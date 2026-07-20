import { apiBase } from "../config";
import type { AttachmentRef } from "../attachments";
import { iterateChatChunks, iterateSseJson } from "../sse/parseChatStream";
import type { ChatChunk, TurnSegment } from "../sse/types";

export type ProfileRow = {
  name: string;
  description?: string;
  slug?: string;
  mcp_servers?: string[];
  native_tool_groups?: string[];
  skills?: string[];
};

export function baseUserHeaders(userId: string, token?: string | null): Record<string, string> {
  const h: Record<string, string> = { "X-AION-User-Id": userId };
  const secret = process.env.NEXT_PUBLIC_AION_CHAT_UI_SECRET?.trim();
  if (secret) h["X-AION-Chat-Ui-Secret"] = secret;
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

export function jsonHeaders(userId: string, token?: string | null): HeadersInit {
  return { ...baseUserHeaders(userId, token), "Content-Type": "application/json" };
}

export async function fetchProfiles(userId: string, token?: string | null): Promise<ProfileRow[]> {
  const r = await fetch(`${apiBase()}/profiles`, { headers: baseUserHeaders(userId, token) });
  if (!r.ok) return [{ name: "Generic Assistant", description: "Fallback", slug: "generic_assistant" }];
  return r.json();
}

export async function listSessionUploads(sessionId: string, userId: string, token?: string | null): Promise<AttachmentRef[]> {
  const r = await fetch(`${apiBase()}/sessions/${encodeURIComponent(sessionId)}/files?subdir=uploads`, {
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) return [];
  const j = (await r.json()) as { files?: Array<{ relative_path?: string; name?: string; mime?: string }> };
  const out: AttachmentRef[] = [];
  for (const row of j.files || []) {
    const rp = row.relative_path;
    if (!rp) continue;
    out.push({
      relative_path: rp,
      original_name: row.name,
      mime: row.mime,
    });
  }
  return out;
}

export async function uploadSessionFiles(sessionId: string, userId: string, files: File[], token?: string | null): Promise<AttachmentRef[]> {
  if (!files.length) return [];
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const h: Record<string, string> = { "X-AION-User-Id": userId };
  const secret = process.env.NEXT_PUBLIC_AION_CHAT_UI_SECRET?.trim();
  if (secret) h["X-AION-Chat-Ui-Secret"] = secret;
  if (token) h.Authorization = `Bearer ${token}`;
  const r = await fetch(`${apiBase()}/sessions/${encodeURIComponent(sessionId)}/upload`, {
    method: "POST",
    headers: h,
    body: fd,
  });
  if (!r.ok) return [];
  const j = (await r.json()) as { files?: Array<Record<string, string>> };
  const attachments: AttachmentRef[] = [];
  for (const item of j.files || []) {
    attachments.push({
      relative_path: item.relative_path,
      original_relative_path: item.original_relative_path,
      original_name: item.original_name,
      mime: item.mime,
    });
  }
  return attachments;
}

export type ChatRequestBody = {
  message: string;
  session_id: string;
  profile: string;
  user_id: string;
  reasoning_effort?: string;
  thinking_enabled?: boolean;
  /** Full session attachment context for the agent (merged uploads + prior session files). */
  attachments?: AttachmentRef[];
  /** Files uploaded in this turn only (persisted on the user message). */
  turn_attachments?: AttachmentRef[];
  user_message_id?: string;
  assistant_message_id?: string;
  message_source?: "user_input" | "internal_trigger";
  web_search_enabled?: boolean;
  web_search_restrict_hosts?: string[];
  agent_mode?: string;
  plan_mode?: boolean;
  deep_research_mode?: boolean;
  /** SQL QueryMemory project slug (cassetti). */
  sql_query_project?: string;
  /** LLM provider slug to use for this chat session. */
  llm_provider_name?: string;
  metadata?: Record<string, any>;
};


export type ChatPrepareMcpError = {
  server_slug: string;
  display_name: string;
  error?: string;
  hint?: string;
  message?: string;
  reason?: string;
};

export type ChatPrepareStatus = {
  ok: boolean;
  status: "idle" | "warming" | "ready" | "failed";
  conversation_id: string;
  mcp_errors?: ChatPrepareMcpError[];
  has_errors?: boolean;
};

export async function fetchChatPrepareStatus(
  conversationId: string,
  profile: string,
  userId: string,
  token?: string | null
): Promise<ChatPrepareStatus | null> {
  const q = new URLSearchParams({
    conversation_id: conversationId,
    profile,
    user_id: userId,
  });
  const r = await fetch(`${apiBase()}/v1/chat/prepare/status?${q}`, {
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) return null;
  return (await r.json()) as ChatPrepareStatus;
}

/** Pre-warm MCP workers + agent cache; polls until ready/failed or timeout. */
export async function waitForChatPrepare(
  conversationId: string,
  profile: string,
  userId: string,
  token?: string | null,
  agentMode?: string,
  opts?: { timeoutMs?: number; pollMs?: number; signal?: AbortSignal; llmProviderName?: string }
): Promise<ChatPrepareStatus | null> {
  const timeoutMs = opts?.timeoutMs ?? 120_000;
  const pollMs = opts?.pollMs ?? 800;
  const started = Date.now();

  try {
    const kick = await fetch(`${apiBase()}/v1/chat/prepare`, {
      method: "POST",
      headers: jsonHeaders(userId, token),
      body: JSON.stringify({
        conversation_id: conversationId,
        profile,
        user_id: userId,
        agent_mode: agentMode ?? "normal",
        llm_provider_name: opts?.llmProviderName,
      }),
      signal: opts?.signal,
    });
    if (!kick.ok) return null;
  } catch {
    return null;
  }

  while (Date.now() - started < timeoutMs) {
    if (opts?.signal?.aborted) return null;
    const snap = await fetchChatPrepareStatus(conversationId, profile, userId, token);
    if (!snap) return null;
    if (snap.status !== "warming") return snap;
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }
  return fetchChatPrepareStatus(conversationId, profile, userId, token);
}

export async function postChatStream(
  body: ChatRequestBody,
  token?: string | null,
  signal?: AbortSignal
): Promise<ReadableStream<Uint8Array> | null> {
  const { session_id, ...rest } = body;
  const r = await fetch(`${apiBase()}/v1/chat/stream`, {
    method: "POST",
    headers: {
      ...jsonHeaders(body.user_id, token),
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ ...rest, conversation_id: session_id }),
    signal,
    cache: "no-store",
  });
  if (!r.ok) {
    throw new Error(`Chat HTTP ${r.status}`);
  }
  return r.body;
}

export async function getChatStreamReconnect(
  conversationId: string,
  userId: string,
  token?: string | null,
  signal?: AbortSignal
): Promise<ReadableStream<Uint8Array> | null> {
  const r = await fetch(
    `${apiBase()}/v1/chat/stream/reconnect/${encodeURIComponent(conversationId)}`,
    {
      headers: {
        ...baseUserHeaders(userId, token),
        Accept: "text/event-stream",
      },
      signal,
      cache: "no-store",
    }
  );
  if (!r.ok) {
    throw new Error(`Chat HTTP ${r.status}`);
  }
  return r.body;
}

export async function consumeChatStream(
  stream: ReadableStream<Uint8Array> | null,
  onChunk: (c: ChatChunk) => void
): Promise<void> {
  for await (const chunk of iterateChatChunks(stream)) {
    onChunk(chunk);
  }
}

export type SessionChart = {
  query?: string;
  data?: Array<Record<string, unknown>>;
  chart_kind?: "line" | "area" | "bar";
  x_key?: string;
  series_keys?: string[];
  stacked?: boolean;
  y_label?: string;
  legend_off?: boolean;
  range_seconds?: number;
  step_seconds?: number;
};

export async function fetchSessionCharts(sessionId: string, userId: string, token?: string | null): Promise<SessionChart[]> {
  const r = await fetch(`${apiBase()}/sessions/${encodeURIComponent(sessionId)}/charts`, {
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) return [];
  const j = (await r.json()) as { charts?: SessionChart[] };
  return j.charts || [];
}

export type SessionFileRow = {
  relative_path?: string;
  name?: string;
  mime?: string;
  size_bytes?: number;
};

export async function listSessionFilesSubdir(
  sessionId: string,
  userId: string,
  subdir: "uploads" | "workspace" | "derived" | "",
  token?: string | null
): Promise<SessionFileRow[]> {
  const r = await fetch(
    `${apiBase()}/sessions/${encodeURIComponent(sessionId)}/files?subdir=${encodeURIComponent(subdir)}`,
    { headers: baseUserHeaders(userId, token) }
  );
  if (!r.ok) return [];
  const j = (await r.json()) as { files?: SessionFileRow[] };
  return j.files || [];
}

/**
 * URL diretto per il download di un file di sessione.
 *
 * NB: il download avviene tramite navigazione browser (anchor href / window.open),
 * che NON puo' impostare l'header ``Authorization``. Per questo, quando il login
 * chat e' attivo, il token va passato come query string ``?access_token=...``:
 * ``require_chat_auth`` lato backend lo legge da ``Query`` esattamente come per
 * l'SSE ``/events/stream``.
 *
 * Se il chiamante non ha (ancora) un token disponibile (es. modalita' senza
 * password auth) l'URL ritornato funziona comunque: il backend accetta
 * richieste anonime quando ``AION_CHAT_PASSWORD_AUTH=0``.
 */
export function sessionDownloadUrl(
  sessionId: string,
  relativePath: string,
  token?: string | null,
): string {
  const q = encodeURIComponent(relativePath);
  const base = `${apiBase()}/sessions/${encodeURIComponent(sessionId)}/download?relative_path=${q}`;
  if (!token) return base;
  return `${base}&access_token=${encodeURIComponent(token)}`;
}

export async function chatStop(sessionId: string, userId: string, token?: string | null): Promise<void> {
  await fetch(`${apiBase()}/v1/chat/stop?session_id=${encodeURIComponent(sessionId)}`, {
    method: "POST",
    headers: jsonHeaders(userId, token),
  });
}

export type ConversationSummary = {
  id: string;
  profile_slug: string;
  title?: string | null;
  message_count?: number;
  metadata?: Record<string, any>;
  updated_at?: string | null;
};

export async function listChatUiConversations(userId: string, token?: string | null): Promise<ConversationSummary[]> {
  const r = await fetch(`${apiBase()}/chat-ui/conversations?limit=80&exclude_scheduled=true`, {
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) return [];
  const j = (await r.json()) as { data?: ConversationSummary[] };
  return j.data || [];
}

export type ChatHistoryStep = {
  id: string;
  name: string;
  type: string;
  input?: string;
  output?: string;
  is_error: boolean;
  created_at: string;
};

export type ChatHistoryArtifact = {
  id: string;
  storage_key: string;
  original_name: string;
  mime: string;
  size_bytes: number;
  kind: string;
  created_at: string;
};

/** API/history timeline — same discriminated union as live SSE segments (`lib/sse/types`). */
export type TimelineSegment = TurnSegment;

export type ChatHistoryMessage = {
  id: string;
  role: string;
  content: string;
  reasoning?: string;
  tool_name?: string;
  tool_call_id?: string;
  created_at: string;
  seq: number;
  steps?: ChatHistoryStep[];
  artifacts?: ChatHistoryArtifact[];
  /** Interleaved display order (additive API field). */
  timeline?: TimelineSegment[] | null;
  metadata?: {
    plan_id?: string;
    plan_task_id?: string;
  };
  rating?: number | null;
  feedback_comment?: string | null;
};

export type StreamStatusResponse = {
  active: boolean;
  assistant_message_id?: string;
  user_message_id?: string;
  profile_name?: string;
  started_at?: number;
};

export async function fetchStreamStatus(
  conversationId: string,
  userId: string,
  token?: string | null,
  signal?: AbortSignal
): Promise<StreamStatusResponse> {
  const r = await fetch(
    `${apiBase()}/chat-ui/conversations/${encodeURIComponent(conversationId)}/stream-status`,
    { headers: baseUserHeaders(userId, token), signal }
  );
  if (!r.ok) return { active: false };
  return (await r.json()) as StreamStatusResponse;
}

export type ConversationHistoryResult =
  | { ok: true; messages: ChatHistoryMessage[] }
  | { ok: false; status: number; error: string; messages: ChatHistoryMessage[] };

export async function fetchConversationHistory(
  conversationId: string,
  userId: string,
  token?: string | null,
  signal?: AbortSignal,
  opts?: { includePlanInternal?: boolean },
): Promise<ConversationHistoryResult> {
  try {
    const qs = opts?.includePlanInternal ? "?include_plan_internal=1" : "";
    const r = await fetch(
      `${apiBase()}/chat-ui/conversations/${encodeURIComponent(conversationId)}/messages${qs}`,
      {
        headers: baseUserHeaders(userId, token),
        signal,
      },
    );
    if (!r.ok) {
      let detail = r.statusText || `HTTP ${r.status}`;
      try {
        const errBody = (await r.json()) as { detail?: string };
        if (errBody?.detail) detail = String(errBody.detail);
      } catch {
        /* ignore */
      }
      return { ok: false, status: r.status, error: detail, messages: [] };
    }
    const j = (await r.json()) as { messages?: ChatHistoryMessage[] };
    return { ok: true, messages: j.messages || [] };
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, status: 0, error: msg, messages: [] };
  }
}

export async function createChatUiConversation(
  userId: string,
  profile: string,
  token?: string | null,
  title?: string
): Promise<ConversationSummary | null> {
  const r = await fetch(`${apiBase()}/chat-ui/conversations`, {
    method: "POST",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify({ profile_name: profile, title: title ?? null }),
  });
  if (!r.ok) return null;
  return r.json();
}

export async function openSessionEventsStream(
  sessionId: string,
  userId: string,
  token?: string | null,
  signal?: AbortSignal
): Promise<ReadableStream<Uint8Array> | null> {
  const r = await fetch(`${apiBase()}/sessions/${encodeURIComponent(sessionId)}/events/stream`, {
    headers: baseUserHeaders(userId, token),
    signal,
  });
  if (!r.ok) return null;
  return r.body;
}

function isAbortError(e: unknown): boolean {
  return (
    (e instanceof DOMException && e.name === "AbortError") ||
    (e instanceof Error && e.name === "AbortError")
  );
}

/** Consuma SSE JSON sessione; il callback è atteso per evento (ordine deterministico, no race su internal_trigger). */
export async function drainSessionEventsLoop(
  body: ReadableStream<Uint8Array> | null,
  cb: (ev: Record<string, unknown>) => void | Promise<void>
): Promise<void> {
  for await (const obj of iterateSseJson(body)) {
    try {
      await cb(obj);
    } catch (err: unknown) {
      if (isAbortError(err)) return;
      console.error("session event handler", err);
    }
  }
}

export async function fetchConversationDetails(
  conversationId: string,
  userId: string,
  token?: string | null
): Promise<any | null> {
  const r = await fetch(`${apiBase()}/chat-ui/conversations/${encodeURIComponent(conversationId)}`, {
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) return null;
  return r.json();
}

export async function updateConversationMetadata(
  conversationId: string,
  metadata: Record<string, any>,
  userId: string,
  token?: string | null
): Promise<any | null> {
  const r = await fetch(`${apiBase()}/chat-ui/conversations/${encodeURIComponent(conversationId)}/metadata`, {
    method: "PATCH",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify({ metadata }),
  });
  if (!r.ok) return null;
  return r.json();
}

export async function updateConversationProfile(
  conversationId: string,
  profile: string,
  userId: string,
  token?: string | null
): Promise<unknown> {
  const r = await fetch(`${apiBase()}/chat-ui/conversations/${encodeURIComponent(conversationId)}/metadata`, {
    method: "PATCH",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify({ profile }),
  });
  if (!r.ok) return null;
  return r.json();
}

export async function updateConversationTitle(
  conversationId: string,
  title: string,
  userId: string,
  token?: string | null
): Promise<any | null> {
  const r = await fetch(`${apiBase()}/chat-ui/conversations/${encodeURIComponent(conversationId)}/metadata`, {
    method: "PATCH",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify({ title }),
  });
  if (!r.ok) return null;
  return r.json();
}

export async function deleteConversation(
  conversationId: string,
  userId: string,
  token?: string | null
): Promise<{ success: boolean } | null> {
  const r = await fetch(`${apiBase()}/chat-ui/conversations/${encodeURIComponent(conversationId)}`, {
    method: "DELETE",
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) return null;
  return r.json();
}


export async function saveChatMessage(
  conversationId: string,
  messageId: string,
  role: "user" | "assistant",
  content: string,
  userId: string,
  token?: string | null,
  reasoning?: string,
  timeline?: TimelineSegment[],
): Promise<{ saved: boolean; message_id?: string; reason?: string }> {
  try {
    const r = await fetch(
      `${apiBase()}/chat-ui/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: "POST",
        headers: jsonHeaders(userId, token),
        body: JSON.stringify({
          message_id: messageId,
          role,
          content,
          reasoning: reasoning ?? null,
          timeline: timeline?.length ? timeline : undefined,
        }),
      }
    );
    if (!r.ok) return { saved: false };
    return r.json();
  } catch {
    return { saved: false };
  }
}

/**
 * @deprecated Server persists assistant messages via TurnPersistence. Kept for plan-summary exception.
 */
export async function saveAssistantMessage(
  conversationId: string,
  messageId: string,
  content: string,
  reasoning: string | undefined,
  userId: string,
  token?: string | null,
  timeline?: TimelineSegment[],
): Promise<{ saved: boolean; message_id?: string; reason?: string }> {
  return saveChatMessage(
    conversationId,
    messageId,
    "assistant",
    content,
    userId,
    token,
    reasoning,
    timeline,
  );
}

export type PartialStep = {
  name: string;
  type?: string;
  input?: string;
  output?: string;
  is_error?: boolean;
};

export async function rateMessage(
  conversationId: string,
  messageId: string,
  rating: number | null,
  comment: string | null,
  userId: string,
  token?: string | null,
): Promise<{ updated: boolean }> {
  try {
    const r = await fetch(
      `${apiBase()}/chat-ui/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/rate`,
      {
        method: "POST",
        headers: jsonHeaders(userId, token),
        body: JSON.stringify({ rating, comment }),
      },
    );
    if (!r.ok) return { updated: false };
    return (await r.json()) as { updated: boolean };
  } catch {
    return { updated: false };
  }
}


export async function patchMessageTimeline(
  conversationId: string,
  messageId: string,
  timeline: TimelineSegment[],
  userId: string,
  token?: string | null,
): Promise<{ updated: boolean }> {
  if (!timeline.length) return { updated: false };
  try {
    const r = await fetch(
      `${apiBase()}/chat-ui/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/timeline`,
      {
        method: "PATCH",
        headers: jsonHeaders(userId, token),
        body: JSON.stringify({ timeline }),
      },
    );
    if (!r.ok) return { updated: false };
    return (await r.json()) as { updated: boolean };
  } catch {
    return { updated: false };
  }
}

/**
 * @deprecated Server persists tool steps via TurnPersistence. Admin/debug only.
 */
export async function saveMessageSteps(
  conversationId: string,
  messageId: string,
  steps: PartialStep[],
  userId: string,
  token?: string | null,
): Promise<{ saved: number }> {
  if (!steps.length) return { saved: 0 };
  try {
    const r = await fetch(
      `${apiBase()}/chat-ui/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/steps`,
      {
        method: "POST",
        headers: jsonHeaders(userId, token),
        body: JSON.stringify({ steps }),
      }
    );
    if (!r.ok) return { saved: 0 };
    return r.json();
  } catch {
    return { saved: 0 };
  }
}

export type ScheduledJobRow = {
  job_id: string;
  name: string;
  cron_expression: string;
  timezone: string;
  profile_slug: string;
  prompt: string;
  session_mode: string;
  session_id?: string | null;
  sql_query_project?: string | null;
  enabled: boolean;
  next_run_at?: string | null;
  last_run?: { status?: string; started_at?: string } | null;
};

export type ScheduledRunRow = {
  run_id: string;
  status: string;
  started_at?: string;
  finished_at?: string;
  error_message?: string;
  assistant_preview?: string;
  session_id?: string;
  conversation_id?: string;
};

async function cronApiErrorMessage(r: Response): Promise<string> {
  try {
    const j = (await r.json()) as { detail?: string };
    return j.detail || r.statusText;
  } catch {
    return r.statusText || "Request failed";
  }
}

export type CronJobsStatus = {
  cron_enabled: boolean;
  hint?: string | null;
};

export async function fetchCronJobsStatus(): Promise<CronJobsStatus> {
  const r = await fetch(`${apiBase()}/v1/cron-jobs/status`);
  if (!r.ok) {
    return {
      cron_enabled: false,
      hint: "Could not reach the scheduled-jobs API.",
    };
  }
  return r.json();
}

export async function listCronJobs(
  userId: string,
  token?: string | null,
): Promise<ScheduledJobRow[]> {
  const r = await fetch(`${apiBase()}/v1/cron-jobs`, { headers: jsonHeaders(userId, token) });
  if (!r.ok) {
    throw new Error(await cronApiErrorMessage(r));
  }
  const j = (await r.json()) as { jobs?: ScheduledJobRow[] };
  return j.jobs || [];
}

export async function createCronJob(
  userId: string,
  body: {
    name: string;
    cron_expression: string;
    prompt: string;
    profile_slug?: string;
    session_mode?: string;
    sql_query_project?: string | null;
    timezone?: string;
    enabled?: boolean;
  },
  token?: string | null,
): Promise<ScheduledJobRow | null> {
  const r = await fetch(`${apiBase()}/v1/cron-jobs`, {
    method: "POST",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    throw new Error(await cronApiErrorMessage(r));
  }
  return r.json();
}

export async function patchCronJob(
  userId: string,
  jobId: string,
  patch: Record<string, unknown>,
  token?: string | null,
): Promise<ScheduledJobRow | null> {
  const r = await fetch(`${apiBase()}/v1/cron-jobs/${encodeURIComponent(jobId)}`, {
    method: "PATCH",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify(patch),
  });
  if (!r.ok) return null;
  return r.json();
}

export async function deleteCronJob(
  userId: string,
  jobId: string,
  token?: string | null,
): Promise<boolean> {
  const r = await fetch(`${apiBase()}/v1/cron-jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
    headers: jsonHeaders(userId, token),
  });
  return r.ok;
}

export async function runCronJobNow(
  userId: string,
  jobId: string,
  token?: string | null,
): Promise<Record<string, unknown> | null> {
  const r = await fetch(`${apiBase()}/v1/cron-jobs/${encodeURIComponent(jobId)}/run-now`, {
    method: "POST",
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) return null;
  return r.json();
}

export async function listCronJobRuns(
  userId: string,
  jobId: string,
  token?: string | null,
): Promise<ScheduledRunRow[]> {
  const r = await fetch(`${apiBase()}/v1/cron-jobs/${encodeURIComponent(jobId)}/runs`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) return [];
  const j = (await r.json()) as { runs?: ScheduledRunRow[] };
  return j.runs || [];
}

export async function fetchKhubFileContent(
  filePath: string,
  userId: string,
  token?: string | null
): Promise<Blob> {
  const r = await fetch(
    `${apiBase()}/chat-ui/khub/file?path=${encodeURIComponent(filePath)}`,
    {
      headers: baseUserHeaders(userId, token),
    }
  );
  if (!r.ok) {
    const txt = await r.text();
    throw new Error(txt || `Impossibile caricare il file (Errore ${r.status})`);
  }
  return r.blob();
}

/** Orchestration plan SSOT (tool-first / DB). */
export type OrchestrationPlanTask = {
  id: string;
  title: string;
  description?: string;
  depends_on?: string[];
  target_profile?: string | null;
  status?: string;
};

export type OrchestrationPlanPayload = {
  goal: string;
  tasks: OrchestrationPlanTask[];
  context?: string;
};

export type OrchestrationPlanState = {
  plan_id: string;
  status: string;
  revision: number;
  markdown: string;
  locked: boolean;
  plan?: OrchestrationPlanPayload;
  todos?: unknown[];
  annotations?: Record<string, unknown>;
};

function orchestrationPath(base: string, subpath: string): string {
  const root = base.replace(/\/$/, "");
  return `${root}/internal/orchestration${subpath}`;
}

export type SessionOrchestrationPlanSummary = {
  plan_id: string;
  status: string;
  revision: number;
};

export async function listSessionOrchestrationPlans(
  apiBaseUrl: string,
  sessionId: string,
  userId: string,
  token?: string | null,
): Promise<SessionOrchestrationPlanSummary[]> {
  const r = await fetch(
    orchestrationPath(apiBaseUrl, `/sessions/${encodeURIComponent(sessionId)}/plans`),
    { method: "GET", headers: jsonHeaders(userId, token) },
  );
  if (!r.ok) return [];
  const j = (await r.json()) as { plans?: SessionOrchestrationPlanSummary[] };
  return j.plans || [];
}

export async function fetchOrchestrationPlan(
  apiBaseUrl: string,
  planId: string,
  sessionId: string,
  userId: string,
  token?: string | null,
): Promise<OrchestrationPlanState | null> {
  const r = await fetch(
    `${orchestrationPath(apiBaseUrl, `/plans/${encodeURIComponent(planId)}`)}?session_id=${encodeURIComponent(sessionId)}`,
    { method: "GET", headers: jsonHeaders(userId, token) },
  );
  if (!r.ok) return null;
  return r.json();
}

export type PlanDecisionBody = {
  session_id: string;
  approved_markdown?: string;
  approved_plan?: OrchestrationPlanPayload;
  todos?: unknown[];
  annotations?: Record<string, unknown>;
  approve_only?: boolean;
  reason?: string;
  user_id?: string;
  profile_name?: string;
};

export async function approveOrchestrationPlan(
  apiBaseUrl: string,
  planId: string,
  body: PlanDecisionBody,
  userId: string,
  token?: string | null,
): Promise<Response> {
  return fetch(orchestrationPath(apiBaseUrl, `/plans/${encodeURIComponent(planId)}/approve`), {
    method: "POST",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify(body),
  });
}

export async function rejectOrchestrationPlan(
  apiBaseUrl: string,
  planId: string,
  body: PlanDecisionBody,
  userId: string,
  token?: string | null,
): Promise<Response> {
  return fetch(orchestrationPath(apiBaseUrl, `/plans/${encodeURIComponent(planId)}/reject`), {
    method: "POST",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify(body),
  });
}

export async function completeOrchestrationTask(
  apiBaseUrl: string,
  planId: string,
  taskId: string,
  sessionId: string,
  userId: string,
  token?: string | null,
): Promise<Response> {
  return fetch(
    orchestrationPath(apiBaseUrl, `/plans/${encodeURIComponent(planId)}/tasks/${encodeURIComponent(taskId)}/complete`),
    {
      method: "POST",
      headers: jsonHeaders(userId, token),
      body: JSON.stringify({ session_id: sessionId }),
    },
  );
}

export async function completeAllOrchestrationTasks(
  apiBaseUrl: string,
  planId: string,
  sessionId: string,
  userId: string,
  token?: string | null,
): Promise<Response> {
  return fetch(orchestrationPath(apiBaseUrl, `/plans/${encodeURIComponent(planId)}/tasks/complete-all`), {
    method: "POST",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify({ session_id: sessionId }),
  });
}

export async function fetchPromptSnapshots(
  sessionId: string,
  userId: string,
  token?: string | null
): Promise<{ enabled: boolean; snapshots: Record<string, unknown>[] }> {
  const q = new URLSearchParams({ session_id: sessionId });
  const r = await fetch(`${apiBase()}/debug/prompt-snapshots?${q.toString()}`, {
    headers: baseUserHeaders(userId, token),
  });
  if (!r.ok) return { enabled: false, snapshots: [] };
  return r.json();
}


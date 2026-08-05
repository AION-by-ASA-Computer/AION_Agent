import { apiBase } from "../config";
import { jsonHeaders } from "./aion";

export type ProjectNote = {
  id: number;
  seq: number;
  content: string;
  category: string;
  importance: number;
  status: string;
  created_at?: string | null;
  superseded_by?: number | null;
  source_session_id?: string | null;
};

export type ProjectMemoryStatus = {
  project: string;
  tenant_id: string;
  scope_type?: string;
  scope_key?: string;
  notes_total: number;
  notes_active: number;
  notes_superseded?: number;
  digests_ready: number;
  digests_total?: number;
  digests_stale?: number;
  seq_count?: number;
  digest_levels?: Record<string, number>;
};

export type ProjectDigest = {
  lo: number;
  hi: number;
  level: number;
  ready: boolean;
  summary: string;
  updated_at?: string | null;
};

export type DigestZoomNode = {
  kind: "digest" | "note";
  lo?: number;
  hi?: number;
  seq?: number;
  line: string;
};

export type DigestZoomResult = {
  digest?: {
    lo: number;
    hi: number;
    ready: boolean;
    summary?: string | null;
  };
  left?: DigestZoomNode[];
  right?: DigestZoomNode[];
  error?: string;
  lo?: number;
  hi?: number;
};

export type WakePreviewRow = {
  kind: "digest" | "note";
  lo?: number;
  hi?: number;
  seq?: number;
  line: string;
};

export const NOTE_CATEGORIES = [
  "preference",
  "fact",
  "event",
  "decision",
  "pitfall",
  "task",
] as const;

async function parseError(r: Response): Promise<string> {
  try {
    const j = (await r.json()) as { detail?: string };
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* ignore */
  }
  return `HTTP ${r.status}`;
}

export async function fetchProjectMemoryStatus(
  userId: string,
  project: string,
  token?: string | null
): Promise<ProjectMemoryStatus> {
  const params = new URLSearchParams({ project });
  const r = await fetch(`${apiBase()}/v1/project-memory/status?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function fetchProjectNotes(
  userId: string,
  project: string,
  token?: string | null,
  opts?: { category?: string; status?: string; limit?: number; offset?: number }
): Promise<ProjectNote[]> {
  const params = new URLSearchParams({
    project,
    status: opts?.status === "" || opts?.status === "all" ? "all" : (opts?.status ?? "active"),
  });
  if (opts?.category) params.set("category", opts.category);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  const r = await fetch(`${apiBase()}/v1/project-memory/notes?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function searchProjectNotes(
  userId: string,
  project: string,
  q: string,
  token?: string | null,
  opts?: { mode?: string; limit?: number }
): Promise<ProjectNote[]> {
  const params = new URLSearchParams({ project, q, mode: opts?.mode ?? "current" });
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  const r = await fetch(`${apiBase()}/v1/project-memory/notes/search?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function fetchProjectNote(
  userId: string,
  project: string,
  noteId: number,
  token?: string | null
): Promise<ProjectNote> {
  const params = new URLSearchParams({ project });
  const r = await fetch(`${apiBase()}/v1/project-memory/notes/${noteId}?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function fetchProjectDigests(
  userId: string,
  project: string,
  token?: string | null,
  opts?: { readyOnly?: boolean | null }
): Promise<ProjectDigest[]> {
  const params = new URLSearchParams({ project });
  if (opts?.readyOnly === true) params.set("ready_only", "true");
  if (opts?.readyOnly === false) params.set("ready_only", "false");
  const r = await fetch(`${apiBase()}/v1/project-memory/digests?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function zoomProjectDigest(
  userId: string,
  project: string,
  lo: number,
  hi: number,
  token?: string | null
): Promise<DigestZoomResult> {
  const params = new URLSearchParams({
    project,
    lo: String(lo),
    hi: String(hi),
  });
  const r = await fetch(`${apiBase()}/v1/project-memory/digests/zoom?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function fetchWakePreview(
  userId: string,
  project: string,
  token?: string | null,
  budget?: number
): Promise<{ rows: WakePreviewRow[]; budget?: number | null }> {
  const params = new URLSearchParams({ project });
  if (budget != null) params.set("budget", String(budget));
  const r = await fetch(`${apiBase()}/v1/project-memory/wake-preview?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function compressProjectMemory(
  userId: string,
  project: string,
  token?: string | null
): Promise<{ compressed: number }> {
  const params = new URLSearchParams({ project });
  const r = await fetch(`${apiBase()}/v1/project-memory/compress?${params}`, {
    method: "POST",
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function createProjectNote(
  userId: string,
  token: string | null | undefined,
  body: {
    session_id: string;
    project: string;
    content: string;
    category: string;
    importance?: number;
  }
): Promise<ProjectNote> {
  const r = await fetch(`${apiBase()}/v1/project-memory/notes`, {
    method: "POST",
    headers: { ...jsonHeaders(userId, token), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function updateProjectNote(
  userId: string,
  token: string | null | undefined,
  noteId: number,
  body: {
    session_id: string;
    project: string;
    content: string;
    category?: string;
    importance?: number;
  }
): Promise<ProjectNote> {
  const r = await fetch(`${apiBase()}/v1/project-memory/notes/${noteId}`, {
    method: "PATCH",
    headers: { ...jsonHeaders(userId, token), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function deleteProjectNote(
  userId: string,
  token: string | null | undefined,
  noteId: number,
  sessionId: string
): Promise<void> {
  const r = await fetch(`${apiBase()}/v1/project-memory/notes/${noteId}`, {
    method: "DELETE",
    headers: { ...jsonHeaders(userId, token), "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, note_id: noteId }),
  });
  if (!r.ok) throw new Error(await parseError(r));
}

import { apiBase } from "../config";
import { jsonHeaders } from "./aion";
import type {
  DigestZoomResult,
  ProjectDigest,
  ProjectMemoryStatus,
  ProjectNote,
  WakePreviewRow,
} from "./project-memory";

export type { ProjectNote as UserNote, ProjectDigest, DigestZoomResult, WakePreviewRow };
export type UserMemoryStatus = ProjectMemoryStatus & { user_id?: string };

export { NOTE_CATEGORIES } from "./project-memory";

async function parseError(r: Response): Promise<string> {
  try {
    const j = (await r.json()) as { detail?: string };
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* ignore */
  }
  return `HTTP ${r.status}`;
}

export async function fetchUserMemoryStatus(
  userId: string,
  token?: string | null
): Promise<UserMemoryStatus> {
  const r = await fetch(`${apiBase()}/v1/user-memory/status`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function fetchUserNotes(
  userId: string,
  token?: string | null,
  opts?: { category?: string; status?: string; limit?: number; offset?: number }
): Promise<ProjectNote[]> {
  const params = new URLSearchParams({
    status: opts?.status === "" || opts?.status === "all" ? "all" : (opts?.status ?? "active"),
  });
  if (opts?.category) params.set("category", opts.category);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  const r = await fetch(`${apiBase()}/v1/user-memory/notes?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function searchUserNotes(
  userId: string,
  q: string,
  token?: string | null,
  opts?: { mode?: string; limit?: number }
): Promise<ProjectNote[]> {
  const params = new URLSearchParams({ q, mode: opts?.mode ?? "current" });
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  const r = await fetch(`${apiBase()}/v1/user-memory/notes/search?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function fetchUserDigests(
  userId: string,
  token?: string | null,
  opts?: { readyOnly?: boolean | null }
): Promise<ProjectDigest[]> {
  const params = new URLSearchParams();
  if (opts?.readyOnly === true) params.set("ready_only", "true");
  if (opts?.readyOnly === false) params.set("ready_only", "false");
  const qs = params.toString();
  const r = await fetch(`${apiBase()}/v1/user-memory/digests${qs ? `?${qs}` : ""}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function zoomUserDigest(
  userId: string,
  lo: number,
  hi: number,
  token?: string | null
): Promise<DigestZoomResult> {
  const params = new URLSearchParams({ lo: String(lo), hi: String(hi) });
  const r = await fetch(`${apiBase()}/v1/user-memory/digests/zoom?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function fetchUserWakePreview(
  userId: string,
  token?: string | null,
  budget?: number
): Promise<{ rows: WakePreviewRow[]; budget?: number | null }> {
  const params = new URLSearchParams();
  if (budget != null) params.set("budget", String(budget));
  const qs = params.toString();
  const r = await fetch(
    `${apiBase()}/v1/user-memory/wake-preview${qs ? `?${qs}` : ""}`,
    { headers: jsonHeaders(userId, token) }
  );
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function compressUserMemory(
  userId: string,
  token?: string | null
): Promise<{ compressed: number }> {
  const r = await fetch(`${apiBase()}/v1/user-memory/compress`, {
    method: "POST",
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function createUserNote(
  userId: string,
  token: string | null | undefined,
  body: {
    session_id: string;
    content: string;
    category: string;
    importance?: number;
  }
): Promise<ProjectNote> {
  const r = await fetch(`${apiBase()}/v1/user-memory/notes`, {
    method: "POST",
    headers: { ...jsonHeaders(userId, token), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function updateUserNote(
  userId: string,
  token: string | null | undefined,
  noteId: number,
  body: {
    session_id: string;
    content: string;
    category?: string;
    importance?: number;
  }
): Promise<ProjectNote> {
  const r = await fetch(`${apiBase()}/v1/user-memory/notes/${noteId}`, {
    method: "PATCH",
    headers: { ...jsonHeaders(userId, token), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function deleteUserNote(
  userId: string,
  token: string | null | undefined,
  noteId: number,
  sessionId: string
): Promise<void> {
  const r = await fetch(`${apiBase()}/v1/user-memory/notes/${noteId}`, {
    method: "DELETE",
    headers: { ...jsonHeaders(userId, token), "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, note_id: noteId }),
  });
  if (!r.ok) throw new Error(await parseError(r));
}

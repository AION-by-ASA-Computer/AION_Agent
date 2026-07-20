import { apiBase } from "../config";
import { jsonHeaders } from "./aion";

export type NavigationDrawer = {
  id?: string;
  drawer_id?: string;
  wing?: string;
  room?: string;
  preview?: string;
  content?: string;
  content_preview?: string;
  text?: string;
};

export type NavigationStatus = {
  enabled: boolean;
  project_slug: string;
  wing: string;
  rooms: string[];
  drawer_count: number;
  sample_drawers?: NavigationDrawer[];
  wings?: Record<string, number>;
};

async function parseError(r: Response): Promise<string> {
  try {
    const j = (await r.json()) as { detail?: string };
    if (typeof j.detail === "string") return j.detail;
  } catch {
    /* ignore */
  }
  return `HTTP ${r.status}`;
}

export async function fetchNavigationStatus(
  userId: string,
  sessionId: string,
  project: string,
  token?: string | null
): Promise<NavigationStatus> {
  const params = new URLSearchParams({
    project,
    session_id: sessionId,
  });
  const r = await fetch(`${apiBase()}/v1/navigation-memory/status?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function fetchNavigationDrawerDetail(
  userId: string,
  sessionId: string,
  drawerId: string,
  token?: string | null
): Promise<NavigationDrawer> {
  const params = new URLSearchParams({
    drawer_id: drawerId,
    session_id: sessionId,
  });
  const r = await fetch(`${apiBase()}/v1/navigation-memory/drawers/detail?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function fetchNavigationDrawers(
  userId: string,
  sessionId: string,
  project: string,
  token?: string | null,
  opts?: { room?: string; limit?: number; wing?: string }
): Promise<{ drawers: NavigationDrawer[]; wing: string }> {
  const params = new URLSearchParams({
    project,
    session_id: sessionId,
  });
  if (opts?.wing) params.set("wing", opts.wing);
  if (opts?.room) params.set("room", opts.room);
  if (opts?.limit) params.set("limit", String(opts.limit));
  const r = await fetch(`${apiBase()}/v1/navigation-memory/drawers?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function searchNavigationMemory(
  userId: string,
  sessionId: string,
  project: string,
  q: string,
  token?: string | null,
  opts?: { room?: string; limit?: number; wing?: string }
): Promise<{ results: NavigationDrawer[] }> {
  const params = new URLSearchParams({
    project,
    session_id: sessionId,
    q,
  });
  if (opts?.wing) params.set("wing", opts.wing);
  if (opts?.room) params.set("room", opts.room);
  if (opts?.limit) params.set("limit", String(opts.limit));
  const r = await fetch(`${apiBase()}/v1/navigation-memory/search?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

export async function upsertNavigationDrawer(
  userId: string,
  sessionId: string,
  body: {
    project: string;
    room: string;
    content: string;
    drawer_id?: string;
  },
  token?: string | null
): Promise<void> {
  const r = await fetch(`${apiBase()}/v1/navigation-memory/drawers/upsert`, {
    method: "POST",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify({ session_id: sessionId, ...body }),
  });
  if (!r.ok) throw new Error(await parseError(r));
}

export async function deleteNavigationDrawer(
  userId: string,
  sessionId: string,
  drawerId: string,
  token?: string | null
): Promise<void> {
  const r = await fetch(`${apiBase()}/v1/navigation-memory/drawers/delete`, {
    method: "POST",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify({ session_id: sessionId, drawer_id: drawerId }),
  });
  if (!r.ok) throw new Error(await parseError(r));
}

export async function pruneLegacyNavigationWings(
  userId: string,
  sessionId: string,
  token?: string | null,
  opts?: { dry_run?: boolean; include_agent_procedures?: boolean }
): Promise<{ pruned_wings: string[]; kept_wings: string[]; dry_run: boolean }> {
  const r = await fetch(`${apiBase()}/v1/navigation-memory/prune-legacy`, {
    method: "POST",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify({
      session_id: sessionId,
      dry_run: opts?.dry_run !== false,
      include_agent_procedures: opts?.include_agent_procedures === true,
    }),
  });
  if (!r.ok) throw new Error(await parseError(r));
  return r.json();
}

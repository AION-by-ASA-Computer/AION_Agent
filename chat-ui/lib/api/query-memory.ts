import { apiBase } from "../config";
import { jsonHeaders } from "./aion";

export type SqlProject = {
  id: number;
  slug: string;
  display_name: string;
  description?: string | null;
  scope_mode?: string;
  role?: string | null;
};

export type SqlProjectMember = {
  user_identifier: string;
  role: string;
  invited_by?: string | null;
};

export type SqlQueryRow = {
  id: number;
  user_request: string;
  sql_text: string;
  is_verified: boolean;
  success_count: number;
  project_slug?: string;
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

function profileQ(profileSlug?: string): string {
  return profileSlug ? `?profile=${encodeURIComponent(profileSlug)}` : "";
}

export async function fetchSqlProjects(
  userId: string,
  token?: string | null,
  profileSlug?: string
): Promise<SqlProject[]> {
  const r = await fetch(`${apiBase()}/v1/query-memory/projects${profileQ(profileSlug)}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) {
    throw new Error(await parseError(r));
  }
  return r.json();
}

export async function createSqlProject(
  userId: string,
  body: { slug: string; display_name: string; description?: string },
  token?: string | null,
  profileSlug?: string
): Promise<SqlProject> {
  const r = await fetch(`${apiBase()}/v1/query-memory/projects${profileQ(profileSlug)}`, {
    method: "POST",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    throw new Error(await parseError(r));
  }
  return r.json();
}

export async function patchSqlProject(
  userId: string,
  projectSlug: string,
  body: { display_name?: string; description?: string },
  token?: string | null
): Promise<SqlProject> {
  const r = await fetch(
    `${apiBase()}/v1/query-memory/projects/${encodeURIComponent(projectSlug)}`,
    {
      method: "PATCH",
      headers: jsonHeaders(userId, token),
      body: JSON.stringify(body),
    }
  );
  if (!r.ok) {
    throw new Error(await parseError(r));
  }
  return r.json();
}

export async function fetchSqlProjectMembers(
  userId: string,
  projectSlug: string,
  token?: string | null
): Promise<SqlProjectMember[]> {
  const r = await fetch(
    `${apiBase()}/v1/query-memory/projects/${encodeURIComponent(projectSlug)}/members`,
    { headers: jsonHeaders(userId, token) }
  );
  if (!r.ok) {
    throw new Error(await parseError(r));
  }
  return r.json();
}

export async function inviteSqlProjectMember(
  userId: string,
  projectSlug: string,
  memberIdentifier: string,
  token?: string | null
): Promise<SqlProjectMember> {
  const r = await fetch(
    `${apiBase()}/v1/query-memory/projects/${encodeURIComponent(projectSlug)}/members`,
    {
      method: "POST",
      headers: jsonHeaders(userId, token),
      body: JSON.stringify({ user_identifier: memberIdentifier }),
    }
  );
  if (!r.ok) {
    throw new Error(await parseError(r));
  }
  return r.json();
}

export async function removeSqlProjectMember(
  userId: string,
  projectSlug: string,
  memberIdentifier: string,
  token?: string | null
): Promise<void> {
  const r = await fetch(
    `${apiBase()}/v1/query-memory/projects/${encodeURIComponent(projectSlug)}/members/${encodeURIComponent(memberIdentifier)}`,
    { method: "DELETE", headers: jsonHeaders(userId, token) }
  );
  if (!r.ok) {
    throw new Error(await parseError(r));
  }
}

export async function fetchSqlQueries(
  userId: string,
  project: string,
  token?: string | null,
  opts?: { q?: string; verified_only?: boolean; limit?: number }
): Promise<SqlQueryRow[]> {
  const params = new URLSearchParams({ project });
  if (opts?.q) params.set("q", opts.q);
  if (opts?.verified_only) params.set("verified_only", "true");
  if (opts?.limit) params.set("limit", String(opts.limit));
  const r = await fetch(`${apiBase()}/v1/query-memory/queries?${params}`, {
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) {
    throw new Error(await parseError(r));
  }
  return r.json();
}

export async function patchSqlQuery(
  userId: string,
  id: number,
  body: { user_request?: string; sql_text?: string; is_verified?: boolean },
  token?: string | null
): Promise<void> {
  const r = await fetch(`${apiBase()}/v1/query-memory/queries/${id}`, {
    method: "PATCH",
    headers: jsonHeaders(userId, token),
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    throw new Error(await parseError(r));
  }
}

export async function deleteSqlQuery(
  userId: string,
  id: number,
  token?: string | null
): Promise<void> {
  const r = await fetch(`${apiBase()}/v1/query-memory/queries/${id}`, {
    method: "DELETE",
    headers: jsonHeaders(userId, token),
  });
  if (!r.ok) {
    throw new Error(await parseError(r));
  }
}

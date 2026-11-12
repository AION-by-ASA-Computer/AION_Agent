/**
 * Client helpers for the one-click AION upgrade (`/admin/update/*`).
 *
 * The backend proxies these calls to the `aion-updater` sidecar, which runs
 * `install.sh upgrade` hop by hop. Used by `VersionUpdateBanner`,
 * `UpdateConfirmDialog` and `UpdateProgressOverlay`.
 * Docs: docs/deployment/self-update.md
 */

import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";

/** One step of the upgrade chain; `release_url` is null for the final `local` hop. */
export type UpdateHop = { version: string; release_url: string | null };

/** Hop plan computed by `install.sh upgrade --plan` in the sidecar. */
export type UpdatePlan = {
  current: string;
  target: string;
  latest_release?: string | null;
  chain: string[];
  hops: UpdateHop[];
  update_available: boolean;
  /** "github" (GHCR releases only) or "hybrid-local" (releases + final local build). */
  mode?: string;
};

/** Upgrade phases written by install.sh's `_progress` (see do_upgrade). */
export type UpdatePhase =
  | "starting"
  | "plan"
  | "backup"
  | "fetch"
  | "build"
  | "pull"
  | "migrate"
  | "restart"
  | "health"
  | "done";

/** Content of `data/updater/status.json` plus the log tail, as returned by the sidecar. */
export type UpdateStatus = {
  /** False when the sidecar is not deployed/reachable: the feature is hidden. */
  supported: boolean;
  reason?: string;
  state?: "idle" | "running" | "succeeded" | "failed";
  phase?: UpdatePhase | string;
  current?: string;
  target?: string;
  chain?: string[];
  /** 1-based index of the hop in progress. */
  hop_index?: number;
  hop_from?: string;
  hop_to?: string;
  completed?: string[];
  error?: string;
  backup?: string;
  started_at?: string;
  finished_at?: string;
  requested_by?: string | null;
  log_tail?: string[];
};

/** Window event fired when an upgrade has been started (the overlay listens to it). */
export const UPDATE_STARTED_EVENT = "aion:update-started";

/** Error returned by `startUpdate`; `code` comes from the backend/sidecar (e.g. `upgrade_running`). */
export type UpdateStartError = { code: string; message: string };

/**
 * Current upgrade status, or null when the API is unreachable.
 *
 * Null is expected while an upgrade restarts the backend/Caddy (network error
 * or 502): callers keep the last known status and retry.
 */
export async function fetchUpdateStatus(): Promise<UpdateStatus | null> {
  try {
    const res = await apiFetch(`${apiBase()}/admin/update/status`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as UpdateStatus;
  } catch {
    return null;
  }
}

/** Fresh hop plan (bypasses the sidecar cache). Throws an `UpdateStartError`-shaped object on failure. */
export async function fetchUpdatePlan(): Promise<UpdatePlan> {
  const res = await apiFetch(`${apiBase()}/admin/update/plan?refresh=true`, { cache: "no-store" });
  if (!res.ok) throw await readError(res);
  return (await res.json()) as UpdatePlan;
}

/** Start the upgrade; resolves with the initial status or rejects with an `UpdateStartError`. */
export async function startUpdate(): Promise<UpdateStatus> {
  const res = await apiFetch(`${apiBase()}/admin/update/start`, { method: "POST" });
  if (!res.ok) throw await readError(res);
  return (await res.json()) as UpdateStatus;
}

/** Normalize a FastAPI error body (`{detail: {code, message}}`) into an `UpdateStartError`. */
async function readError(res: Response): Promise<UpdateStartError> {
  const body = await res.json().catch(() => null);
  const detail = body?.detail;
  if (detail && typeof detail === "object") {
    return { code: String(detail.code || `http_${res.status}`), message: String(detail.message || "") };
  }
  return { code: `http_${res.status}`, message: typeof detail === "string" ? detail : "" };
}

/** True for released versions (X.Y.Z): only those have a GitHub release page. */
export function isSemver(version: string | undefined | null): boolean {
  return !!version && /^\d+\.\d+\.\d+$/.test(version);
}

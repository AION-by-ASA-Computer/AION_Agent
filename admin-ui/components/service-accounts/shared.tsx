"use client";

/**
 * Shared types, limits and small helpers for the Service accounts admin page
 * (`app/service-accounts/page.tsx`) and its dialogs.
 *
 * The shapes mirror the backend contract of `/admin/service-accounts*`; the
 * limits mirror the server-side validation so the forms can reject bad input
 * before a round trip (the backend stays authoritative).
 */

import { cn } from "@/lib/cn";
import { getLocale } from "@/lib/i18n/i18n-store";
import { readApiErrorMessage } from "@/lib/apiErrors";

/** i18n namespace of the page. */
export const k = "admin_service_accounts";

export type T = (key: string, vars?: Record<string, string | number>) => string;

/** One row of `GET /admin/service-accounts`. */
export interface ServiceAccount {
  id: string;
  identifier: string;
  display_name?: string | null;
  description?: string | null;
  disabled: boolean;
  disabled_at?: string | null;
  ltm_enabled: boolean;
  max_api_keys: number;
  api_key_max_ttl_days: number;
  active_keys: number;
  last_used_at?: string | null;
  created_at?: string | null;
  created_by?: string | null;
  profiles?: string[];
}

/** Key policy returned next to the key list by `GET /admin/service-accounts/{id}/keys`. */
export interface KeyPolicy {
  enabled: boolean;
  max_keys: number;
  active_count: number;
  max_ttl_days: number;
  allowed_scopes: string[];
}

/** One API key of a service account; the secret itself is never listed. */
export interface ServiceKey {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  created_at?: string | null;
  expires_at?: string | null;
  last_used_at?: string | null;
  revoked_at?: string | null;
  status: "active" | "expired" | "revoked";
}

/** Key just created: the only response that ever carries the full secret. */
export type CreatedKey = ServiceKey & { key: string };

/** Identifier prefix the backend adds to every service account slug. */
export const SVC_PREFIX = "svc-";

/** Same rule the backend enforces on the slug (`svc-` is added server side). */
export const SLUG_RE = /^[a-z0-9][a-z0-9._-]{1,60}$/;

/** Account policy ranges and the defaults the backend applies on create. */
export const MAX_KEYS = { min: 1, max: 100, default: 5 };
export const KEY_TTL_DAYS = { min: 1, max: 365, default: 90 };

/** Fallback scope list when the backend policy does not send one (same as user API keys). */
export const DEFAULT_SCOPES = ["chat", "conversations:read", "conversations:write", "files:read", "files:write"];

/** i18n-safe key for a scope name (":" would read oddly in JSON keys). */
export const scopeKey = (scope: string) => scope.replace(/[^a-z0-9]+/gi, "_");

/** Translated scope label, falling back to the raw scope for ones the UI does not know yet. */
export function scopeLabel(t: T, scope: string): string {
  const key = `${k}.scopes.${scopeKey(scope)}`;
  const label = t(key);
  return label === key ? scope : label;
}

/** Whole number within the range, or null when the text isn't one. */
export function parseInRange(text: string, range: { min: number; max: number }): number | null {
  if (!/^\d+$/.test(text.trim())) return null;
  const n = Number(text);
  return n >= range.min && n <= range.max ? n : null;
}

export const nameOf = (a: ServiceAccount) => a.display_name || a.identifier;

export const formatDate = (iso: string) => new Date(iso).toLocaleString(getLocale(), { dateStyle: "medium", timeStyle: "short" });

/**
 * Error of a failed admin call, split into a machine `code` (from
 * `detail.code` or a string `detail`) and a readable `message`.
 * Reads the body once, so call it instead of `res.json()` on failures.
 */
export async function readError(res: Response): Promise<{ code: string; message: string; detail: Record<string, unknown> | null }> {
  const message = await readApiErrorMessage(res.clone(), `HTTP ${res.status}`);
  try {
    const body = await res.json();
    const d = body?.detail;
    if (d && typeof d === "object" && !Array.isArray(d)) {
      return { code: typeof d.code === "string" ? d.code : "", message, detail: d as Record<string, unknown> };
    }
    return { code: typeof d === "string" ? d : "", message, detail: null };
  } catch {
    return { code: "", message, detail: null };
  }
}

/** Status pill used for both accounts (active / disabled) and keys (active / expired / revoked). */
export function StatusBadge({ tone, label }: { tone: "success" | "muted" | "warning" | "danger"; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
        tone === "success" && "bg-success/12 text-success",
        tone === "muted" && "bg-secondary text-muted-foreground",
        tone === "warning" && "bg-warning/15 text-warning",
        tone === "danger" && "bg-destructive/10 text-destructive",
      )}
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
      {label}
    </span>
  );
}

/** Labelled form field with an optional hint (or error) line under the control. */
export function Field({
  label,
  htmlFor,
  optional,
  hint,
  error,
  t,
  children,
}: {
  label: string;
  htmlFor: string;
  optional?: boolean;
  hint?: string;
  /** Replaces the hint in red when set. */
  error?: string;
  t: T;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={htmlFor} className="flex items-baseline justify-between gap-2 text-sm font-medium">
        {label}
        {optional && <span className="text-xs font-normal text-muted-foreground">{t(`${k}.form.optional`)}</span>}
      </label>
      {children}
      {(error || hint) && (
        <span id={`${htmlFor}-hint`} className={cn("text-xs", error ? "text-destructive" : "text-muted-foreground")}>
          {error || hint}
        </span>
      )}
    </div>
  );
}

"use client";

/**
 * Shared pieces of the admin Telegram page (`app/telegram/page.tsx`): API row types,
 * the JSON reader that turns backend error codes into `Error.message`, and the small
 * loading / user-label helpers used by the config panel and the three lists.
 */

import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import type { useT } from "@/lib/i18n/use-t";

/** i18n namespace of the whole Telegram page. */
export const k = "admin_telegram";

export type T = ReturnType<typeof useT>;
export type Notify = (message: string, variant?: "success" | "error" | "warning" | "info") => void;

/** An AION user as the Telegram admin endpoints return it. */
export type UserRef = { row_id: string; identifier?: string; display_name?: string | null; tg_username?: string | null };

/** Best human label for a user: display name, then identifier, then row id. */
export const userLabel = (u?: UserRef | null) => (u ? u.display_name || u.identifier || u.row_id : "—");

/**
 * Parse a JSON response, throwing on non-2xx. The thrown message is the backend's
 * `detail` code (e.g. `new_owner_not_linked`) so callers can map it to `admin_telegram.err.*`.
 */
export async function readJson<R>(res: Response): Promise<R> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = (body as { detail?: { code?: string } | string }).detail;
    throw new Error(typeof detail === "string" ? detail : detail?.code || String(res.status));
  }
  return res.json() as Promise<R>;
}

/** Centered spinner shown while one of the page's lists is loading. */
export function Loading({ t }: { t: T }) {
  return (
    <p className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground" role="status">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {t(`${k}.loading`)}
    </p>
  );
}

/** Dashed placeholder for an empty list. */
export function EmptyList({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-2xl border border-dashed border-border px-5 py-12 text-center text-sm text-muted-foreground">
      {children}
    </p>
  );
}

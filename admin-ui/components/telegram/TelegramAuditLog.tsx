"use client";

/**
 * "Activity log" section of the admin Telegram page: the latest 200 audit events
 * (linking, bot lifecycle, quota changes) from `GET /admin/telegram/audit`.
 * The list scrolls inside a capped box so it never pushes the page out of reach.
 */

import { useEffect, useState } from "react";
import { apiBase } from "@/lib/api";
import { apiFetch } from "@/lib/api/headers";
import { fullWhen, toMs } from "@/lib/datetime";
import { EmptyList, Loading, k, readJson, userLabel, type T, type UserRef } from "./shared";

type AuditRow = {
  id: number;
  ts: string | null;
  action: string;
  user: UserRef | null;
  actor_tg_user_id: number | null;
  payload: Record<string, unknown>;
};

/** @param rev bumped by the page after a config save, which itself may log events. */
export function TelegramAuditLog({ t, rev }: { t: T; rev: number }) {
  const [rows, setRows] = useState<AuditRow[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch(`${apiBase()}/admin/telegram/audit?limit=200`)
      .then((r) => readJson<{ data: AuditRow[] }>(r))
      .then((data) => {
        if (!cancelled) setRows(data.data);
      })
      .catch(() => {
        if (!cancelled) setRows([]);
      });
    return () => {
      cancelled = true;
    };
  }, [rev]);

  if (!rows) return <Loading t={t} />;
  if (rows.length === 0) return <EmptyList>{t(`${k}.audit_empty`)}</EmptyList>;

  // Unknown actions (newer backend) fall back to the raw action code.
  const label = (action: string) => {
    const key = `${k}.audit.${action}`;
    const txt = t(key);
    return txt === key ? action : txt;
  };
  return (
    <ul className="max-h-[32rem] divide-y divide-border/60 overflow-y-auto overscroll-contain rounded-2xl border border-border bg-card/60">
      {rows.map((r) => {
        const details = Object.entries(r.payload || {})
          .filter(([, v]) => v !== null && v !== "")
          .map(([key, v]) => `${key}: ${String(v)}`)
          .join(" · ");
        return (
          <li key={r.id} className="flex flex-col gap-0.5 px-5 py-3 sm:flex-row sm:items-baseline sm:gap-4">
            <time className="shrink-0 text-xs tabular-nums text-muted-foreground sm:w-40" dateTime={r.ts || undefined}>
              {fullWhen(toMs(r.ts))}
            </time>
            <span className="text-sm font-medium">{label(r.action)}</span>
            <span className="min-w-0 truncate text-xs text-muted-foreground">
              {[r.user ? userLabel(r.user) : null, details].filter(Boolean).join(" · ")}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

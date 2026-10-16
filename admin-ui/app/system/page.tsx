"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Database, HardDrive, Loader2, RefreshCw, Server } from "lucide-react";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { getLocale } from "@/lib/i18n/i18n-store";
import { outlineBtn } from "@/components/ui/classes";

const k = "admin_system";
const REFRESH_MS = 30000;

type Health = {
  redis?: { connected?: boolean; fallback_active?: boolean; type?: string; url?: string; namespace?: string };
  database?: { url?: string; size_bytes?: number; unified?: boolean };
  storage?: { backend?: string; local_root?: string };
};

type Tone = "ok" | "warn" | "bad";
const DOT: Record<Tone, string> = { ok: "bg-success", warn: "bg-warning", bad: "bg-destructive" };
const TEXT: Record<Tone, string> = { ok: "text-success", warn: "text-warning", bad: "text-destructive" };

function Status({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm font-medium", TEXT[tone])}>
      <span className={cn("h-2 w-2 rounded-full", DOT[tone])} aria-hidden />
      {label}
    </span>
  );
}

function Component({
  icon: Icon,
  title,
  hint,
  status,
  rows,
  footer,
}: {
  icon: typeof Server;
  title: string;
  hint: string;
  status: React.ReactNode;
  rows: { label: string; value: React.ReactNode }[];
  footer?: string;
}) {
  return (
    <li className="grid gap-x-8 gap-y-4 px-5 py-5 md:grid-cols-[minmax(0,16rem)_minmax(0,1fr)]">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-secondary text-muted-foreground">
          <Icon className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{title}</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
          <div className="mt-2">{status}</div>
        </div>
      </div>
      <div className="min-w-0">
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-2.5 text-sm">
          {rows.map((r) => (
            <div key={r.label} className="col-span-2 grid grid-cols-subgrid items-baseline">
              <dt className="text-muted-foreground">{r.label}</dt>
              <dd className="min-w-0 break-words text-right font-medium tabular-nums">{r.value}</dd>
            </div>
          ))}
        </dl>
        {footer && <p className="mt-3 truncate border-t border-border/50 pt-3 font-mono text-xs text-muted-foreground" title={footer}>{footer}</p>}
      </div>
    </li>
  );
}

export default function SystemHealth() {
  const t = useT();
  const locale = getLocale();
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    apiFetch(`${apiBase()}/admin/system/health`)
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.json();
      })
      .then((data: Health) => {
        setHealth(data);
        setFailed(false);
        setUpdatedAt(new Date());
      })
      .catch(() => setFailed(true))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const time = useMemo(
    () => (updatedAt ? new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(updatedAt) : null),
    [updatedAt, locale],
  );

  const redis = health?.redis;
  const db = health?.database;
  const storage = health?.storage;

  const redisTone: Tone = !redis ? "bad" : redis.fallback_active ? "warn" : redis.connected ? "ok" : "bad";
  const dbTone: Tone = db?.unified ? "ok" : "warn";
  const overall: Tone = [redisTone, dbTone].includes("bad") ? "bad" : [redisTone, dbTone].includes("warn") ? "warn" : "ok";
  const sizeMb = db && typeof db.size_bytes === "number" && db.size_bytes > 0 ? `${(db.size_bytes / 1024 / 1024).toFixed(2)} MB` : t(`${k}.na`);

  const firstLoad = loading && !health;

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <header className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">{t(`${k}.title`)}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
            {health ? (
              <>
                <span className={cn("h-2 w-2 shrink-0 rounded-full", DOT[overall])} aria-hidden />
                <span>{t(`${k}.overall.${overall}`)}</span>
              </>
            ) : (
              <span>{t(`${k}.subtitle`)}</span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {time && <span className="hidden text-xs tabular-nums text-muted-foreground md:inline">{t(`${k}.updated_at`, { time })}</span>}
          <button type="button" className={outlineBtn} onClick={load} disabled={loading}>
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} aria-hidden />
            {t(`${k}.refresh`)}
          </button>
        </div>
      </header>

      {failed && !health ? (
        <div className="flex flex-col items-start gap-3 rounded-3xl border border-dashed border-border px-6 py-14">
          <p className="text-sm text-destructive" role="alert">
            {t(`${k}.error`)}
          </p>
          <button type="button" className={outlineBtn} onClick={load}>
            {t(`${k}.retry`)}
          </button>
        </div>
      ) : firstLoad ? (
        <div className="flex items-center gap-2 px-1 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t(`${k}.loading`)}
        </div>
      ) : (
        <>
          {failed && (
            <p className="-mt-2 text-sm text-warning" role="status">
              {t(`${k}.stale`)}
            </p>
          )}
          <section className="overflow-hidden rounded-3xl border border-border/60 bg-card/40" aria-labelledby="system-components-title">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-5 pb-3 pt-4">
              <h2 id="system-components-title" className="text-sm font-semibold">
                {t(`${k}.components`)}
              </h2>
              <span className="text-xs text-muted-foreground">{t(`${k}.auto_refresh`, { n: REFRESH_MS / 1000 })}</span>
            </div>
            <ul className="divide-y divide-border/40 border-t border-border/50">
              <Component
                icon={Server}
                title={t(`${k}.redis.title`)}
                hint={t(`${k}.redis.hint`)}
                status={<Status tone={redisTone} label={t(`${k}.redis.status_${redis?.fallback_active ? "fallback" : redis?.connected ? "up" : "down"}`)} />}
                rows={[
                  { label: t(`${k}.redis.type`), value: redis?.type || t(`${k}.na`) },
                  { label: t(`${k}.redis.fallback`), value: <span className={redis?.fallback_active ? "text-warning" : ""}>{t(`${k}.${redis?.fallback_active ? "active" : "inactive"}`)}</span> },
                  ...(redis?.namespace ? [{ label: t(`${k}.redis.namespace`), value: <span className="font-mono text-[13px]">{redis.namespace}</span> }] : []),
                ]}
                footer={redis?.url}
              />
              <Component
                icon={Database}
                title={t(`${k}.db.title`)}
                hint={t(`${k}.db.hint`)}
                status={<Status tone={dbTone} label={t(`${k}.db.status_${db?.unified ? "unified" : "split"}`)} />}
                rows={[
                  { label: t(`${k}.db.unified`), value: t(`${k}.${db?.unified ? "enabled" : "disabled"}`) },
                  { label: t(`${k}.db.size`), value: sizeMb },
                ]}
                footer={db?.url}
              />
              <Component
                icon={HardDrive}
                title={t(`${k}.storage.title`)}
                hint={t(`${k}.storage.hint`)}
                status={<Status tone="ok" label={t(`${k}.storage.status_${storage?.backend === "s3" ? "s3" : "local"}`)} />}
                rows={[
                  { label: t(`${k}.storage.backend`), value: <span className="uppercase">{storage?.backend || t(`${k}.na`)}</span> },
                  { label: t(`${k}.storage.root`), value: <span className="font-mono text-[13px]">{storage?.local_root || t(`${k}.na`)}</span> },
                ]}
              />
            </ul>
          </section>
        </>
      )}
    </div>
  );
}

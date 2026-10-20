"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Loader2, Lock, RefreshCw, ThumbsDown, ThumbsUp } from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { getLocale } from "@/lib/i18n/i18n-store";
import { apiFetch } from "@/lib/api/headers";
import { apiBase } from "@/lib/api";
import { outlineBtn } from "@/components/ui/classes";
import { EmptyRow, Panel } from "@/components/metrics/Tables";
import type { FeedbackCounts, FeedbackSummary } from "@/components/dashboard/useDashboardData";

const k = "admin_feedback";
const WINDOWS = [7, 30, 90, 365] as const;
/** Below this many ratings an approval rate is noise, so it is shown without a verdict colour. */
const MIN_SAMPLE = 5;

type T = ReturnType<typeof useT>;
type Row = FeedbackCounts & { id: string; name: string };

function approval(c: FeedbackCounts): number | null {
  const total = c.positive + c.negative;
  return total ? (c.positive / total) * 100 : null;
}

function tone(c: FeedbackCounts): "ok" | "warn" | "bad" | "few" {
  const rate = approval(c);
  if (rate === null || c.positive + c.negative < MIN_SAMPLE) return "few";
  return rate >= 80 ? "ok" : rate >= 60 ? "warn" : "bad";
}

/** Positive share on the left, negative on the right: the proportion is the reading, not the colour. */
function SplitBar({ c, className }: { c: FeedbackCounts; className?: string }) {
  const total = c.positive + c.negative;
  const pos = total ? (c.positive / total) * 100 : 0;
  return (
    <div className={cn("flex h-1.5 overflow-hidden rounded-full bg-secondary", className)} aria-hidden>
      {total > 0 && (
        <>
          <span className="h-full bg-success/80" style={{ width: `${pos}%` }} />
          <span className="h-full bg-warning/80" style={{ width: `${100 - pos}%` }} />
        </>
      )}
    </div>
  );
}

function Approval({ c, pct, t }: { c: FeedbackCounts; pct: Intl.NumberFormat; t: T }) {
  const rate = approval(c);
  if (rate === null) return <span className="text-muted-foreground">—</span>;
  const tn = tone(c);
  return (
    <span className="inline-flex items-center gap-1.5 tabular-nums" title={tn === "few" ? t(`${k}.few_ratings`, { n: MIN_SAMPLE }) : undefined}>
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          tn === "ok" ? "bg-success" : tn === "warn" ? "bg-warning" : tn === "bad" ? "bg-destructive" : "bg-muted-foreground/40",
        )}
        aria-hidden
      />
      {pct.format(rate / 100)}
    </span>
  );
}

const th = "px-5 py-2 text-xs font-medium text-muted-foreground";
const td = "px-5 py-3 align-middle";

function BreakdownTable({ rows, nameLabel, n, pct, t, empty }: { rows: Row[]; nameLabel: string; n: Intl.NumberFormat; pct: Intl.NumberFormat; t: T; empty: string }) {
  if (rows.length === 0) return <EmptyRow>{empty}</EmptyRow>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] text-sm">
        <thead>
          <tr className="border-y border-border/50 text-left">
            <th scope="col" className={th}>{nameLabel}</th>
            <th scope="col" className={cn(th, "w-44")}>
              <span className="sr-only">{t(`${k}.col.split`)}</span>
            </th>
            <th scope="col" className={cn(th, "text-right")}>{t(`${k}.col.positive`)}</th>
            <th scope="col" className={cn(th, "text-right")}>{t(`${k}.col.negative`)}</th>
            <th scope="col" className={cn(th, "text-right")}>{t(`${k}.col.approval`)}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/40">
          {rows.map((r) => (
            <tr key={r.id} className="transition-colors hover:bg-secondary/40">
              <td className={cn(td, "max-w-[18rem] truncate font-medium")} title={r.name}>
                {r.name}
              </td>
              <td className={td}>
                <SplitBar c={r} className="w-40" />
              </td>
              <td className={cn(td, "text-right tabular-nums")}>{n.format(r.positive)}</td>
              <td className={cn(td, "text-right tabular-nums", r.negative ? "text-warning" : "text-muted-foreground")}>{n.format(r.negative)}</td>
              <td className={cn(td, "text-right")}>
                <Approval c={r} pct={pct} t={t} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function useFeedback(days: number) {
  const [data, setData] = useState<FeedbackSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase()}/admin/feedback?days=${days}`);
      if (!res.ok) throw new Error(String(res.status));
      setData((await res.json()) as FeedbackSummary);
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    const id = setTimeout(() => void load(), 0);
    return () => clearTimeout(id);
  }, [load]);

  return { data, loading, failed, reload: load };
}

export default function FeedbackPage() {
  const t = useT();
  const locale = getLocale();
  const [days, setDays] = useState<number>(30);
  const { data, loading, failed, reload } = useFeedback(days);

  const n = useMemo(() => new Intl.NumberFormat(locale), [locale]);
  const pct = useMemo(() => new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }), [locale]);

  const totals = data?.totals ?? { positive: 0, negative: 0 };
  const total = totals.positive + totals.negative;
  const byProfile: Row[] = (data?.by_profile ?? []).map((r) => ({ id: r.slug || r.profile, name: r.profile, positive: r.positive, negative: r.negative }));
  const byModel: Row[] = (data?.by_model ?? []).map((r) => ({ id: r.model, name: r.model, positive: r.positive, negative: r.negative }));
  const windowLabel = t(`${k}.window_name`, { n: days });
  const firstLoad = loading && !data;

  return (
    <div className="mx-auto flex max-w-[84rem] flex-col gap-6">
      <header className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <h1 className="text-balance text-2xl font-semibold tracking-[-0.02em] sm:text-[28px]">{t(`${k}.title`)}</h1>
          <p className="mt-1 flex items-start gap-2 text-sm text-muted-foreground">
            <Lock className="mt-[3px] h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>{t(`${k}.privacy`)}</span>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label={t(`${k}.window`)} className="inline-flex h-9 items-center rounded-xl border border-border bg-card p-0.5">
            {WINDOWS.map((w) => (
              <button
                key={w}
                type="button"
                aria-pressed={days === w}
                onClick={() => setDays(w)}
                className={cn(
                  "focus-ring h-8 rounded-[10px] px-2.5 text-sm font-medium tabular-nums transition-colors",
                  days === w ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t(`${k}.window_short`, { n: w })}
              </button>
            ))}
          </div>
          <button type="button" className={outlineBtn} onClick={() => void reload()} disabled={loading}>
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} aria-hidden />
            {t(`${k}.refresh`)}
          </button>
        </div>
      </header>

      {failed && !data ? (
        <div className="flex flex-col items-start gap-3 rounded-3xl border border-dashed border-border px-6 py-14">
          <p className="text-sm text-destructive" role="alert">
            {t(`${k}.error`)}
          </p>
          <button type="button" className={outlineBtn} onClick={() => void reload()}>
            {t(`${k}.retry`)}
          </button>
        </div>
      ) : (
        <>
          {failed && (
            <p className="-mt-2 text-sm text-warning" role="status">
              {t(`${k}.stale`)}
            </p>
          )}
          {firstLoad && (
            <div className="flex items-center gap-2 px-1 text-sm text-muted-foreground" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              {t(`${k}.loading`)}
            </div>
          )}

          <section className="rounded-3xl border border-border/60 bg-card/40 px-5 py-5" aria-labelledby="feedback-summary-title">
            <h2 id="feedback-summary-title" className="sr-only">
              {t(`${k}.summary_title`)}
            </h2>
            {data && total === 0 ? (
              <div className="flex flex-col gap-1 py-4">
                <p className="text-sm font-medium">{t(`${k}.empty_title`, { window: windowLabel })}</p>
                <p className="max-w-[65ch] text-sm text-muted-foreground">{t(`${k}.empty_detail`)}</p>
              </div>
            ) : (
              <div className={cn("flex flex-col gap-4 transition-opacity", loading && data && "opacity-60")}>
                <div className="flex flex-wrap items-end gap-x-10 gap-y-4">
                  <div className="flex flex-col gap-0.5">
                    <span className="text-xs text-muted-foreground">{t(`${k}.approval`)}</span>
                    <span className="text-[28px] font-semibold leading-tight tracking-[-0.02em] tabular-nums">
                      {data && total ? pct.format(totals.positive / total) : "—"}
                    </span>
                  </div>
                  <div className="flex flex-col gap-0.5">
                    <span className="text-xs text-muted-foreground">{t(`${k}.col.positive`)}</span>
                    <span className="inline-flex items-center gap-1.5 text-xl font-semibold tabular-nums">
                      <ThumbsUp className="h-4 w-4 text-success" aria-hidden />
                      {data ? n.format(totals.positive) : "—"}
                    </span>
                  </div>
                  <div className="flex flex-col gap-0.5">
                    <span className="text-xs text-muted-foreground">{t(`${k}.col.negative`)}</span>
                    <span className="inline-flex items-center gap-1.5 text-xl font-semibold tabular-nums">
                      <ThumbsDown className={cn("h-4 w-4", totals.negative ? "text-warning" : "text-muted-foreground")} aria-hidden />
                      {data ? n.format(totals.negative) : "—"}
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground sm:ml-auto">
                    {data ? t(`${k}.total`, { count: n.format(total), window: windowLabel }) : ""}
                  </p>
                </div>
                <SplitBar c={totals} className="h-2" />
              </div>
            )}
          </section>

          <div className="grid gap-6 xl:grid-cols-2 xl:items-start">
            <Panel id="feedback-profiles-title" title={t(`${k}.by_profile`)} meta={data ? t(`${k}.count`, { n: byProfile.length }) : undefined}>
              <BreakdownTable rows={byProfile} nameLabel={t(`${k}.col.profile`)} n={n} pct={pct} t={t} empty={t(`${k}.empty_table`, { window: windowLabel })} />
            </Panel>
            <Panel id="feedback-models-title" title={t(`${k}.by_model`)} meta={data ? t(`${k}.count`, { n: byModel.length }) : undefined}>
              <BreakdownTable rows={byModel} nameLabel={t(`${k}.col.model`)} n={n} pct={pct} t={t} empty={t(`${k}.empty_table`, { window: windowLabel })} />
            </Panel>
          </div>

          <p className="text-xs text-muted-foreground">
            {t(`${k}.footnote`, { n: MIN_SAMPLE })}{" "}
            <Link href="/profiles" className="focus-ring rounded underline underline-offset-2 hover:text-foreground">
              {t(`${k}.open_profiles`)}
            </Link>
          </p>
        </>
      )}
    </div>
  );
}

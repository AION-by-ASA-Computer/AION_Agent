"use client";

import Link from "next/link";
import { ArrowRight, ThumbsDown, ThumbsUp } from "lucide-react";
import type { MetricsOverview, SeriesPoint } from "./useDashboardData";

/** Recent history of a headline number; an empty series renders nothing. */
function Trend({ points, label }: { points: SeriesPoint[] | undefined; label: string }) {
  const values = (points ?? []).map((p) => p.value).filter((v) => Number.isFinite(v));
  if (values.length < 2) return <div className="h-8" aria-hidden />;
  const w = 120;
  const h = 32;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const step = w / (values.length - 1);
  const pts = values.map((v, i) => [i * step, h - 2 - ((v - min) / span) * (h - 4)] as const);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-8 w-full max-w-[140px]" role="img" aria-label={label} preserveAspectRatio="none">
      <path d={`${line} L${w} ${h} L0 ${h} Z`} className="fill-foreground/[0.05]" />
      <path d={line} fill="none" className="stroke-muted-foreground/70" strokeWidth={1.25} vectorEffect="non-scaling-stroke" />
      <circle cx={lx} cy={ly} r={2.25} className="fill-primary" />
    </svg>
  );
}

type T = (key: string, vars?: Record<string, string | number>) => string;

export function ActivityPanel({
  metrics,
  feedback,
  locale,
  t,
}: {
  metrics: MetricsOverview | null;
  feedback: { positives: number; negatives: number };
  locale: string;
  t: T;
}) {
  const k = "admin_dashboard.activity";
  const n = new Intl.NumberFormat(locale);
  const compact = new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 });
  const dash = "—";
  const seconds = (v: number | undefined) =>
    v === undefined ? dash : `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(v)} s`;

  const cells = [
    {
      id: "turns",
      label: t(`${k}.turns`),
      value: metrics ? n.format(metrics.total_turns) : dash,
      detail: metrics ? t(`${k}.turns_detail`, { failures: n.format(metrics.total_failures) }) : "",
      series: metrics?.turns_series,
    },
    {
      id: "tokens",
      label: t(`${k}.tokens`),
      value: metrics ? compact.format(metrics.total_tokens) : dash,
      detail: "",
      series: metrics?.tokens_series,
    },
    {
      id: "tools",
      label: t(`${k}.tool_success`),
      value: metrics ? `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(metrics.tool_success_rate)}%` : dash,
      detail: metrics ? t(`${k}.tool_calls`, { count: n.format(metrics.total_tool_calls) }) : "",
      series: undefined,
    },
    {
      id: "duration",
      label: t(`${k}.avg_turn`),
      value: seconds(metrics?.avg_turn_duration_seconds),
      detail: metrics ? t(`${k}.p95`, { value: seconds(metrics.p95_turn_duration_seconds) }) : "",
      series: metrics?.turn_duration_series,
    },
  ];

  return (
    <section className="rounded-3xl border border-border/60 bg-card/40" aria-labelledby="activity-title">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 pt-4">
        <h2 id="activity-title" className="text-sm font-semibold">
          {t(`${k}.title`)}
        </h2>
        <span className="text-xs text-muted-foreground">
          {metrics ? (metrics.prometheus_connected ? t(`${k}.source_prometheus`) : t(`${k}.source_local`)) : t(`${k}.unavailable`)}
        </span>
        <Link
          href="/metrics"
          className="focus-ring ml-auto inline-flex items-center gap-1 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground"
        >
          {t(`${k}.open_metrics`)}
          <ArrowRight className="h-3 w-3" aria-hidden />
        </Link>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-5">
        {cells.map((c, i) => (
          <div
            key={c.id}
            className={
              "flex flex-col gap-1 border-border/50 px-5 py-4 " +
              (i % 2 === 1 ? "border-l " : "") +
              (i >= 2 ? "border-t lg:border-t-0 " : "") +
              (i > 0 ? "lg:border-l" : "")
            }
          >
            <div className="text-xs text-muted-foreground">{c.label}</div>
            <div className="text-xl font-semibold tracking-[-0.01em] tabular-nums">{c.value}</div>
            <div className="min-h-4 text-[11.5px] text-muted-foreground">{c.detail}</div>
            {c.series !== undefined && <Trend points={c.series} label={t(`${k}.trend_label`, { metric: c.label })} />}
          </div>
        ))}
        <Link
          href="/feedback"
          className="focus-ring col-span-2 flex flex-col gap-1 border-t border-border/50 px-5 py-4 transition-colors hover:bg-secondary/40 lg:col-span-1 lg:border-l lg:border-t-0"
        >
          <div className="text-xs text-muted-foreground">{t(`${k}.feedback`)}</div>
          <div className="flex items-center gap-4 text-xl font-semibold tabular-nums">
            <span className="inline-flex items-center gap-1.5">
              <ThumbsUp className="h-4 w-4 text-success" aria-hidden />
              <span className="sr-only">{t(`${k}.positive`)}</span>
              {n.format(feedback.positives)}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <ThumbsDown className={feedback.negatives ? "h-4 w-4 text-warning" : "h-4 w-4 text-muted-foreground"} aria-hidden />
              <span className="sr-only">{t(`${k}.negative`)}</span>
              {n.format(feedback.negatives)}
            </span>
          </div>
          <div className="text-[11.5px] text-muted-foreground">{t(`${k}.feedback_detail`)}</div>
        </Link>
      </div>
    </section>
  );
}

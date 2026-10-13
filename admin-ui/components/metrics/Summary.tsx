"use client";

import { Brain, ArrowDownLeft, ArrowUpRight } from "lucide-react";
import { BarsChart, TrendChart } from "./Charts";
import type { Format } from "./format";
import type { MetricsOverviewData, T } from "./types";

const k = "admin_metrics.summary";

/** Token mix shares one scale everywhere: Input, Output, Reasoning. Named in text so colour never carries it alone. */
export const TOKEN_TONE = { prompt: "bg-foreground/80", completion: "bg-primary", reasoning: "bg-muted-foreground/45" } as const;

export function TokenSplit({ prompt, completion, reasoning, className = "h-1.5" }: { prompt: number; completion: number; reasoning: number; className?: string }) {
  const total = prompt + completion + reasoning;
  if (!total) return <div className={`${className} w-full rounded-full bg-secondary`} aria-hidden />;
  return (
    <div className={`flex ${className} w-full gap-px overflow-hidden rounded-full bg-secondary`} aria-hidden>
      <div className={TOKEN_TONE.prompt} style={{ width: `${(prompt / total) * 100}%` }} />
      <div className={TOKEN_TONE.completion} style={{ width: `${(completion / total) * 100}%` }} />
      <div className={TOKEN_TONE.reasoning} style={{ width: `${(reasoning / total) * 100}%` }} />
    </div>
  );
}

function Cell({ label, value, children, border }: { label: string; value: string; children: React.ReactNode; border: string }) {
  return (
    <div className={`flex flex-col gap-1.5 px-5 py-4 ${border}`}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold tracking-[-0.015em] tabular-nums">{value}</div>
      {children}
    </div>
  );
}

export function Summary({ m, fmt, rangeLabel, stamp, t }: { m: MetricsOverviewData | null; fmt: Format; rangeLabel: string; stamp: (ts: string) => string; t: T }) {
  const lastTurnTokens = m ? m.last_turn_prompt_tokens + m.last_turn_completion_tokens + m.last_turn_reasoning_tokens : 0;
  const chartLabel = (metric: string) => t(`${k}.chart`, { metric });
  const failureTone = m && m.total_failures > 0 ? "font-medium text-destructive" : "";
  const rateTone = m && m.total_tool_calls > 0 ? (m.tool_success_rate >= 95 ? "text-success" : m.tool_success_rate >= 80 ? "text-warning" : "text-destructive") : "";

  return (
    <section className="rounded-3xl border border-border/60 bg-card/40" aria-labelledby="metrics-summary-title">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-5 pt-4">
        <h2 id="metrics-summary-title" className="text-sm font-semibold">
          {t(`${k}.title`)}
        </h2>
        <span className="text-xs text-muted-foreground">{rangeLabel}</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4">
        <Cell label={t(`${k}.tokens`)} value={fmt.compact(m?.total_tokens)} border="">
          <TokenSplit prompt={m?.prompt_tokens ?? 0} completion={m?.completion_tokens ?? 0} reasoning={m?.reasoning_tokens ?? 0} />
          <dl className="grid grid-cols-3 gap-2 text-xs">
            <div>
              <dt className="flex items-center gap-1 text-muted-foreground">
                <ArrowDownLeft className="h-3 w-3" aria-hidden />
                {t(`${k}.input`)}
              </dt>
              <dd className="font-medium tabular-nums">{fmt.compact(m?.prompt_tokens)}</dd>
            </div>
            <div>
              <dt className="flex items-center gap-1 text-muted-foreground">
                <ArrowUpRight className="h-3 w-3" aria-hidden />
                {t(`${k}.output`)}
              </dt>
              <dd className="font-medium tabular-nums">{fmt.compact(m?.completion_tokens)}</dd>
            </div>
            <div>
              <dt className="flex items-center gap-1 text-muted-foreground">
                <Brain className="h-3 w-3" aria-hidden />
                {t(`${k}.reasoning`)}
              </dt>
              <dd className="font-medium tabular-nums">{fmt.compact(m?.reasoning_tokens)}</dd>
            </div>
          </dl>
          <div className="min-h-4 text-xs text-muted-foreground tabular-nums">{m ? t(`${k}.last_turn_tokens`, { n: fmt.compact(lastTurnTokens) }) : ""}</div>
          <TrendChart data={m?.tokens_series} label={chartLabel(t(`${k}.tokens`))} stamp={stamp} format={fmt.compact} tone="text-primary" />
        </Cell>

        <Cell label={t(`${k}.turns`)} value={fmt.int(m?.total_turns)} border="sm:border-l border-t sm:border-t-0 border-border/50">
          <div className="min-h-4 text-xs tabular-nums text-muted-foreground">
            {m && (
              <>
                {t(`${k}.failures`)} <span className={failureTone}>{fmt.int(m.total_failures)}</span>
              </>
            )}
          </div>
          <div className="min-h-4 text-xs text-muted-foreground">{t(`${k}.turns_hint`)}</div>
          <div className="mt-auto pt-2">
            <BarsChart data={m?.turns_series} label={chartLabel(t(`${k}.turns`))} stamp={stamp} format={(v) => t(`${k}.n_turns`, { n: fmt.int(v) })} />
          </div>
        </Cell>

        <Cell label={t(`${k}.tools`)} value={fmt.int(m?.total_tool_calls)} border="xl:border-l border-t xl:border-t-0 border-border/50">
          <div className="min-h-4 text-xs tabular-nums text-muted-foreground">
            {m && (
              <>
                {t(`${k}.success_rate`)} <span className={`font-medium ${rateTone}`}>{m.total_tool_calls > 0 ? fmt.percent(m.tool_success_rate) : "—"}</span>
              </>
            )}
          </div>
          <div className="min-h-4 text-xs text-muted-foreground">{t(`${k}.tools_hint`)}</div>
          <div className="mt-auto pt-2">
            <BarsChart data={m?.tool_calls_series} label={chartLabel(t(`${k}.tools`))} stamp={stamp} format={(v) => t(`${k}.n_calls`, { n: fmt.int(v) })} />
          </div>
        </Cell>

        <Cell label={t(`${k}.duration`)} value={fmt.seconds(m?.avg_turn_duration_seconds)} border="sm:border-l border-t xl:border-t-0 border-border/50">
          <dl className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <dt className="text-muted-foreground">{t(`${k}.p95`)}</dt>
              <dd className="font-medium tabular-nums">{fmt.seconds(m?.p95_turn_duration_seconds)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t(`${k}.last_turn`)}</dt>
              <dd className="font-medium tabular-nums">{fmt.seconds(m?.last_turn_duration_seconds)}</dd>
            </div>
          </dl>
          <div className="min-h-4 text-xs text-muted-foreground">{t(`${k}.duration_hint`)}</div>
          <div className="mt-auto pt-2">
            <TrendChart data={m?.turn_duration_series} label={chartLabel(t(`${k}.duration`))} stamp={stamp} format={fmt.seconds} />
          </div>
        </Cell>
      </div>
    </section>
  );
}

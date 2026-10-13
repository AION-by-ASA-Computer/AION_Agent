"use client";

import { CheckCircle2, Circle, Eye, Loader2, OctagonAlert, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/cn";
import { getLocale } from "@/lib/i18n/i18n-store";
import { ghostBtn } from "@/components/ui/classes";
import { SCENARIOS } from "./scenarioList";
import { scoreTone, toneText } from "./format";
import type { T, TestStatus } from "./types";

const k = "admin_diagnostics.scenarios";
const GRID = "md:grid-cols-[minmax(0,2.2fr)_minmax(0,1.4fr)_5.5rem_4.5rem_5.5rem_8.5rem]";

export const hasResult = (s: TestStatus) => s.status === "completed" || (s.status === "failed" && (s.final_output !== undefined || s.score !== undefined));

function StatusIcon({ s, t }: { s: TestStatus; t: T }) {
  const common = "h-5 w-5 shrink-0";
  if (s.status === "running") return <Loader2 className={cn(common, "animate-spin text-primary")} aria-label={t(`${k}.status.running`)} />;
  if (s.status === "failed" || (s.status === "completed" && s.passed === false))
    return <OctagonAlert className={cn(common, "text-destructive")} aria-label={t(`${k}.status.failed`)} />;
  if (s.status === "completed") return <CheckCircle2 className={cn(common, "text-success")} aria-label={t(`${k}.status.completed`)} />;
  return <Circle className={cn(common, "text-muted-foreground/50")} strokeWidth={1.5} aria-label={t(`${k}.status.idle`)} />;
}

export function Scenarios({ tests, onOpen, t }: { tests: Record<string, TestStatus>; onOpen: (id: string) => void; t: T }) {
  const locale = getLocale();
  const rules = new Intl.PluralRules(locale);
  const num = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  const all = SCENARIOS.map((s) => tests[s.id]);
  const finished = all.filter((s) => s.status === "completed" || s.status === "failed");
  const scored = all.filter((s) => s.score !== undefined);
  const average = scored.length ? Math.round(scored.reduce((sum, s) => sum + (s.score ?? 0), 0) / scored.length) : null;

  const summary = [
    finished.length === 0 ? t(`${k}.summary_idle`) : t(`${k}.summary`, { done: finished.length, total: SCENARIOS.length }),
    average !== null && t(`${k}.summary_score`, { score: average }),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <section aria-labelledby="scenarios-title">
      <div className="mb-3 flex items-baseline gap-3 px-1">
        <h2 id="scenarios-title" className="text-lg font-semibold tracking-[-0.015em]">{t(`${k}.title`)}</h2>
        <span className="text-sm tabular-nums text-muted-foreground">{summary}</span>
      </div>

      <ul className="divide-y divide-border/50 overflow-hidden rounded-3xl border border-border/60 bg-card/40">
        {SCENARIOS.map((sc) => {
          const s = tests[sc.id];
          const Icon = sc.icon;
          const tone = s.score !== undefined ? scoreTone(s.score) : null;
          const toolWord = t(`${k}.tools_${rules.select(s.tool_count) === "one" ? "one" : "other"}`, { count: s.tool_count });
          return (
            <li key={sc.id} className={cn("grid items-center gap-x-4 gap-y-2 px-4 py-3.5 sm:px-5", GRID)}>
              <div className="flex min-w-0 items-center gap-3.5">
                <StatusIcon s={s} t={t} />
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{t(`${k}.item.${sc.key}.name`)}</div>
                  <div className="truncate text-xs text-muted-foreground">{t(`${k}.item.${sc.key}.desc`)}</div>
                </div>
              </div>

              <div className="flex min-w-0 items-center gap-2 pl-8 text-xs text-muted-foreground md:pl-0">
                <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
                <span className="sr-only">{t(`${k}.file_${sc.fileRole}`)}</span>
                <span className="truncate font-mono" title={sc.file}>{sc.file}</span>
              </div>

              <div className="pl-8 text-xs tabular-nums text-muted-foreground md:pl-0">{toolWord}</div>
              <div className="pl-8 text-xs tabular-nums text-muted-foreground md:pl-0">
                {s.duration_sec !== undefined && s.status !== "idle" ? `${num.format(s.duration_sec)}s` : "—"}
              </div>

              <div className="pl-8 text-sm font-semibold tabular-nums md:pl-0">
                {s.score !== undefined && tone ? (
                  <span className={cn("inline-flex items-center gap-1", toneText[tone])}>
                    {tone === "warning" && <TriangleAlert className="h-3.5 w-3.5" aria-hidden />}
                    {s.score}
                    <span className="text-xs font-normal text-muted-foreground">/100</span>
                  </span>
                ) : (
                  <span className="text-muted-foreground/60">—</span>
                )}
              </div>

              <div className="pl-8 md:pl-0 md:text-right">
                {hasResult(s) ? (
                  <button type="button" className={cn(ghostBtn, "-ml-3 md:ml-0")} onClick={() => onOpen(sc.id)}>
                    <Eye className="h-3.5 w-3.5" aria-hidden />
                    {t(`${k}.view_result`)}
                  </button>
                ) : s.status === "running" ? (
                  <span className="text-xs text-primary">{t(`${k}.status.running`)}</span>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

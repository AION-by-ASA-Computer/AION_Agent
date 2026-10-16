"use client";

import { useState } from "react";
import { Check, CheckCircle2, Copy, Download, OctagonAlert } from "lucide-react";
import { cn } from "@/lib/cn";
import { getLocale } from "@/lib/i18n/i18n-store";
import { Dialog } from "@/components/profiles/Dialog";
import { outlineBtn } from "@/components/ui/classes";
import { Markdown } from "./Markdown";
import { SessionCharts, type SessionChart } from "./Charts";
import { Json, toolIcon } from "./Stream";
import { fileUrl } from "./files";
import { clock, kb, scoreTone, toneBar, toneText } from "./format";
import type { T, TestStatus } from "./types";

const k = "admin_diagnostics.result";
type Tab = "final" | "eval" | "charts" | "files" | "timeline" | "reasoning";

function Eval({ s, t }: { s: TestStatus; t: T }) {
  const score = s.score ?? 0;
  const max = s.max_score ?? 100;
  const tone = scoreTone(max ? (score / max) * 100 : score);
  const criteria = Array.isArray(s.eval_criteria) ? s.eval_criteria : [];
  const met = criteria.filter((c) => c?.passed).length;
  return (
    <div className="flex flex-col gap-5">
      <div className="rounded-2xl border border-border/60 bg-card/40 p-4 sm:p-5">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className={cn("text-2xl font-semibold tabular-nums tracking-[-0.02em]", toneText[tone])}>{t(`${k}.score`, { score, max })}</span>
          {s.rating && <span className="text-sm text-muted-foreground">{t(`${k}.grade`, { rating: s.rating })}</span>}
          <span className={cn("inline-flex items-center gap-1 text-sm font-medium", s.passed ? "text-success" : "text-destructive")}>
            {s.passed ? <CheckCircle2 className="h-4 w-4" aria-hidden /> : <OctagonAlert className="h-4 w-4" aria-hidden />}
            {s.passed ? t(`${k}.passed`) : t(`${k}.failed`)}
          </span>
        </div>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-secondary" role="progressbar" aria-valuemin={0} aria-valuemax={max} aria-valuenow={score}>
          <div className={cn("h-full rounded-full", toneBar[tone])} style={{ width: `${Math.min(100, Math.max(0, max ? (score / max) * 100 : 0))}%` }} />
        </div>
        <p className="mt-3 max-w-[70ch] text-sm text-muted-foreground">{s.eval_summary || t(`${k}.eval_default`)}</p>
      </div>

      <div>
        <div className="mb-2 flex items-baseline gap-3 px-1">
          <h4 className="text-sm font-semibold">{t(`${k}.criteria_title`)}</h4>
          <span className="text-xs tabular-nums text-muted-foreground">{t(`${k}.criteria_count`, { passed: met, total: criteria.length })}</span>
        </div>
        {criteria.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">{t(`${k}.criteria_none`)}</p>
        ) : (
          <ul className="divide-y divide-border/50 overflow-hidden rounded-2xl border border-border/60">
            {criteria.map((c, i) => {
              const maxPts = c.max_points ?? c.points_max ?? 10;
              const pts = c.points ?? c.points_awarded ?? (c.passed ? maxPts : 0);
              return (
                <li key={i} className="flex items-start gap-3 px-4 py-3">
                  {c.passed ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-label={t(`${k}.passed`)} />
                  ) : (
                    <OctagonAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-label={t(`${k}.failed`)} />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{c.name}</span>
                      {c.category && <span className="rounded-full bg-secondary px-2 py-0.5 text-xs text-muted-foreground">{c.category}</span>}
                    </div>
                    {c.description && <p className="mt-0.5 text-xs text-muted-foreground">{c.description}</p>}
                    {c.details && <p className="mt-0.5 break-words font-mono text-xs text-muted-foreground">{c.details}</p>}
                  </div>
                  <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{t(`${k}.points`, { points: pts, max: maxPts })}</span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

export function ResultDialog({ test, scenarioName, profile, onClose, t }: { test: TestStatus; scenarioName: string; profile: string; onClose: () => void; t: T }) {
  const locale = getLocale();
  const [tab, setTab] = useState<Tab>("final");
  const [copied, setCopied] = useState(false);

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "final", label: t(`${k}.tab_final`) },
    ...(test.score !== undefined ? [{ id: "eval" as const, label: t(`${k}.tab_eval`), count: undefined }] : []),
    ...(test.charts?.length ? [{ id: "charts" as const, label: t(`${k}.tab_charts`), count: test.charts.length }] : []),
    ...(test.generated_files?.length ? [{ id: "files" as const, label: t(`${k}.tab_files`), count: test.generated_files.length }] : []),
    ...(test.timeline?.length ? [{ id: "timeline" as const, label: t(`${k}.tab_timeline`), count: test.timeline.length }] : []),
    ...(test.reasoning ? [{ id: "reasoning" as const, label: t(`${k}.tab_reasoning`) }] : []),
  ];

  return (
    <Dialog title={scenarioName} closeLabel={t(`${k}.close`)} onClose={onClose} className="max-w-5xl">
      <dl className="mb-4 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
        <div className="flex gap-1.5"><dt>{t(`${k}.meta_profile`)}</dt><dd className="font-mono text-foreground">{test.assistant || profile}</dd></div>
        <div className="flex gap-1.5"><dt>{t(`${k}.meta_duration`)}</dt><dd className="tabular-nums text-foreground">{test.duration_sec ?? "—"}s</dd></div>
        <div className="flex gap-1.5"><dt>{t(`${k}.meta_tools`)}</dt><dd className="tabular-nums text-foreground">{test.tool_count}</dd></div>
        {test.single_report_filename && <div className="flex gap-1.5"><dt>{t(`${k}.report_file`)}</dt><dd className="font-mono text-foreground">{test.single_report_filename}</dd></div>}
      </dl>

      <div role="tablist" aria-label={t(`${k}.tabs_aria`)} className="no-scrollbar flex gap-1 overflow-x-auto border-b border-border">
        {tabs.map((tb) => (
          <button
            key={tb.id}
            type="button"
            role="tab"
            id={`result-tab-${tb.id}`}
            aria-selected={tab === tb.id}
            aria-controls="result-panel"
            onClick={() => setTab(tb.id)}
            className={cn(
              "focus-ring -mb-px flex shrink-0 items-center gap-2 border-b-2 px-3.5 pb-3 pt-1 text-sm font-medium transition-colors",
              tab === tb.id ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {tb.label}
            {tb.count !== undefined && <span className="text-xs tabular-nums text-muted-foreground">{tb.count}</span>}
          </button>
        ))}
      </div>

      <div id="result-panel" role="tabpanel" aria-labelledby={`result-tab-${tab}`} className="max-h-[58vh] overflow-y-auto pt-5">
        {tab === "final" && (
          <div className="flex flex-col gap-3">
            {test.final_output ? (
              <>
                <div className="flex justify-end">
                  <button
                    type="button"
                    className={outlineBtn}
                    onClick={() => {
                      navigator.clipboard.writeText(test.final_output || "");
                      setCopied(true);
                      window.setTimeout(() => setCopied(false), 1600);
                    }}
                  >
                    {copied ? <Check className="h-3.5 w-3.5 text-success" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
                    {copied ? t(`${k}.copied`) : t(`${k}.copy_text`)}
                  </button>
                </div>
                <Markdown className="max-w-[75ch]">{test.final_output}</Markdown>
              </>
            ) : (
              <p className="py-10 text-center text-sm text-muted-foreground">{t(`${k}.no_output`)}</p>
            )}
          </div>
        )}
        {tab === "eval" && <Eval s={test} t={t} />}
        {tab === "charts" && <SessionCharts charts={(test.charts || []) as SessionChart[]} />}
        {tab === "files" && (
          <ul className="grid gap-2 sm:grid-cols-2">
            {test.generated_files?.map((f, i) => (
              <li key={i} className="flex items-center gap-3 rounded-2xl border border-border/60 bg-card/40 px-3.5 py-2.5">
                {toolIcon(f.name)}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium" title={f.name}>{f.name}</div>
                  <div className="truncate text-xs tabular-nums text-muted-foreground">
                    {kb(f.size_bytes, locale)}{f.category ? ` · ${f.category}` : ""}
                  </div>
                </div>
                <a
                  href={fileUrl(f.name, true)}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`${t(`${k}.download`)}: ${f.name}`}
                  className="focus-ring inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                >
                  <Download className="h-4 w-4" aria-hidden />
                </a>
              </li>
            ))}
          </ul>
        )}
        {tab === "timeline" && (
          <ol className="flex flex-col gap-3">
            {test.timeline?.map((ev, i) => (
              <li key={i} className="rounded-2xl border border-border/60 bg-card/40 p-4">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium">
                    {t(`${k}.timeline_step`, { n: i + 1 })} · {ev.type === "reasoning" ? t(`${k}.timeline_reasoning`) : t(`${k}.timeline_tool`, { name: ev.name || "" })}
                  </span>
                  <span className="text-xs tabular-nums text-muted-foreground">{clock(ev.timestamp, locale)}</span>
                </div>
                {ev.content && <p className="mt-2 whitespace-pre-wrap rounded-xl bg-secondary/50 px-3 py-2 text-xs leading-relaxed text-muted-foreground">{ev.content}</p>}
                <div className="mt-2 flex flex-col gap-2">
                  {ev.parameters != null && <Json label={t(`${k}.input`)} value={ev.parameters} />}
                  {ev.result != null && <Json label={t(`${k}.output`)} value={ev.result} />}
                </div>
              </li>
            ))}
          </ol>
        )}
        {tab === "reasoning" && <p className="whitespace-pre-wrap rounded-2xl bg-secondary/50 px-4 py-3 text-xs leading-relaxed text-muted-foreground">{test.reasoning}</p>}
      </div>
    </Dialog>
  );
}

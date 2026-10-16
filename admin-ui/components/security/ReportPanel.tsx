"use client";

import { Check, Download, Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { outlineBtn } from "@/components/ui/classes";
import { Markdown } from "@/components/conversations/Transcript";
import { baseName, stripJson, verdictTone, type Investigation } from "./report";

type T = (key: string, vars?: Record<string, string | number>) => string;
const k = "admin_security";

const TONE_TEXT = { safe: "text-success", suspicious: "text-warning", dangerous: "text-destructive", unknown: "text-muted-foreground" } as const;

export function ReportPanel({
  file,
  agent,
  report,
  data,
  streaming,
  failed,
  onExport,
  t,
}: {
  file: string | null;
  agent: string;
  report: string;
  data: Investigation | null;
  streaming: boolean;
  failed: boolean;
  onExport: () => void;
  t: T;
}) {
  if (!file) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-20 text-center">
        <h3 className="text-base font-semibold tracking-[-0.015em]">{t(`${k}.report.none_title`)}</h3>
        <p className="mt-1.5 max-w-[40ch] text-sm text-muted-foreground">{t(`${k}.report.none_body`)}</p>
      </div>
    );
  }

  const tone = verdictTone(data?.verdict);
  const body = stripJson(report).trim();
  const fixes = data?.fixes ?? [];
  const showVerdict = !streaming && !!report;

  return (
    <>
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border/60 px-5 py-4 sm:px-7">
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-mono text-base font-semibold tracking-[-0.01em]" title={file}>
            {baseName(file)}
          </h2>
          <p className="mt-0.5 flex items-center gap-1.5 text-sm text-muted-foreground" role="status">
            {streaming ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : failed ? null : <Check className="h-3.5 w-3.5 text-success" aria-hidden />}
            {streaming ? t(`${k}.report.analyzing`) : failed ? t(`${k}.report.interrupted`) : t(`${k}.report.done`)}
            <span aria-hidden>·</span>
            <span className="truncate">{t(`${k}.report.by`, { name: agent })}</span>
          </p>
        </div>
        {!streaming && report && (
          <button type="button" className={outlineBtn} onClick={onExport}>
            <Download className="h-3.5 w-3.5" aria-hidden />
            {t(`${k}.report.export`)}
          </button>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-6 sm:px-7" aria-busy={streaming}>
        {showVerdict && (
          <dl className="mb-7 flex flex-wrap items-baseline gap-x-10 gap-y-3 border-b border-border/60 pb-6">
            <div>
              <dt className="text-xs font-medium text-muted-foreground">{t(`${k}.report.verdict`)}</dt>
              <dd className={cn("mt-1 text-2xl font-semibold tracking-[-0.02em]", TONE_TEXT[tone])}>
                {tone === "unknown" ? t(`${k}.report.manual`) : t(`${k}.verdict.${tone}`)}
              </dd>
            </div>
            {data?.risk_score !== undefined && (
              <div>
                <dt className="text-xs font-medium text-muted-foreground">{t(`${k}.report.risk`)}</dt>
                <dd className="mt-1 text-2xl font-semibold tabular-nums tracking-[-0.02em]">{data.risk_score}%</dd>
              </div>
            )}
          </dl>
        )}

        {body ? (
          <div className="max-w-[72ch] text-sm">
            <Markdown text={body} />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{streaming ? t(`${k}.report.init`) : ""}</p>
        )}

        {fixes.length > 0 && !streaming && (
          <section className="mt-8 border-t border-border/60 pt-6" aria-labelledby="mitigations-title">
            <h3 id="mitigations-title" className="text-base font-semibold tracking-[-0.015em]">
              {t(`${k}.report.mitigations`)}
            </h3>
            <ol className="mt-3 max-w-[72ch] divide-y divide-border/50 text-sm">
              {fixes.map((fix, i) => (
                <li key={i} className="flex gap-3 py-3">
                  <span className="w-5 shrink-0 text-right tabular-nums text-muted-foreground">{i + 1}</span>
                  <span className="min-w-0 break-words">{fix}</span>
                </li>
              ))}
            </ol>
          </section>
        )}
      </div>
    </>
  );
}

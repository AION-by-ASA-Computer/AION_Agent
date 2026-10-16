"use client";

import { useState } from "react";
import { CheckCircle2, OctagonAlert } from "lucide-react";
import { Select } from "@/components/ui/Select";
import { Panel, TokenLegend } from "./Tables";
import { TokenSplit } from "./Summary";
import { formatStamp, type Format } from "./format";
import type { MCPCallError, T } from "./types";

const k = "admin_metrics";

export function ModelsPanel({ usage, fmt, range, t }: { usage: Record<string, Record<string, number>>; fmt: Format; range: string; t: T }) {
  const rows = Object.entries(usage)
    .map(([model, u]) => ({ model, prompt: u.prompt || 0, completion: u.completion || 0, reasoning: u.reasoning || 0 }))
    .map((r) => ({ ...r, total: r.prompt + r.completion + r.reasoning }))
    .sort((a, b) => b.total - a.total);

  return (
    <Panel id="metrics-models-title" title={t(`${k}.models.title`)} meta={t(`${k}.models.count`, { n: rows.length })}>
      {rows.length === 0 ? (
        <p className="border-t border-border/50 px-5 py-10 text-center text-sm text-muted-foreground">{t(`${k}.models.empty`, { range })}</p>
      ) : (
        <>
          <ul className="divide-y divide-border/40 border-t border-border/50">
            {rows.map((r) => (
              <li key={r.model} className="flex flex-col gap-2 px-5 py-3.5">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="min-w-0 truncate font-mono text-[13px] font-medium">{r.model}</span>
                  <span className="shrink-0 text-sm font-medium tabular-nums">{t(`${k}.models.tokens`, { n: fmt.compact(r.total) })}</span>
                </div>
                <TokenSplit prompt={r.prompt} completion={r.completion} reasoning={r.reasoning} className="h-1.5" />
                <div className="flex flex-wrap gap-x-4 text-xs tabular-nums text-muted-foreground">
                  <span>{t(`${k}.summary.input`)} {fmt.compact(r.prompt)}</span>
                  <span>{t(`${k}.summary.output`)} {fmt.compact(r.completion)}</span>
                  {r.reasoning > 0 && <span>{t(`${k}.summary.reasoning`)} {fmt.compact(r.reasoning)}</span>}
                </div>
              </li>
            ))}
          </ul>
          <TokenLegend t={t} />
        </>
      )}
    </Panel>
  );
}

const LIMITS = ["5", "10", "25", "50", "all"] as const;

export function ErrorsPanel({ errors, range, locale, t }: { errors: MCPCallError[]; range: string; locale: string; t: T }) {
  const [limit, setLimit] = useState<string>("5");
  const shown = limit === "all" ? errors : errors.slice(0, Number(limit));
  const options = LIMITS.map((v) => ({ value: v, label: v === "all" ? t(`${k}.errors.limit_all`, { n: errors.length }) : t(`${k}.errors.limit_n`, { n: v }) }));

  return (
    <Panel
      id="metrics-errors-title"
      title={t(`${k}.errors.title`)}
      meta={errors.length > 0 ? t(`${k}.errors.count`, { n: errors.length }) : undefined}
      actions={errors.length > 5 ? <Select size="sm" value={limit} onChange={setLimit} options={options} aria-label={t(`${k}.errors.limit_label`)} className="w-40 bg-card" /> : undefined}
    >
      {errors.length === 0 ? (
        <div className="flex items-center gap-3 border-t border-border/50 px-5 py-4 text-sm" role="status">
          <CheckCircle2 className="h-4 w-4 text-success" aria-hidden />
          <span className="font-medium">{t(`${k}.errors.none`)}</span>
          <span className="hidden text-muted-foreground sm:inline">{t(`${k}.errors.none_detail`)}</span>
        </div>
      ) : (
        <ul className="max-h-[26rem] divide-y divide-border/40 overflow-y-auto border-t border-border/50">
          {shown.map((e, i) => (
            <li key={i} className="px-5 py-3.5">
              <div className="flex items-start gap-3">
                <OctagonAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
                    <span className="font-mono text-[13px] font-medium">{e.tool_name}</span>
                    <span className="text-muted-foreground">{e.mcp_server}</span>
                  </div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    {t(`${k}.errors.profile`, { profile: e.profile })}
                    {e.timestamp ? ` · ${formatStamp(e.timestamp, range, locale)}` : ""}
                  </div>
                  {e.error_message && <p className="mt-2 break-words rounded-xl bg-secondary/60 px-3 py-2 font-mono text-xs leading-relaxed">{e.error_message}</p>}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

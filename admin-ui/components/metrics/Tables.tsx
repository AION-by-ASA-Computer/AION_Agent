"use client";

import React, { useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/cn";
import { SearchField } from "@/components/ui/SearchField";
import { TokenSplit } from "./Summary";
import { rateTone, type Format } from "./format";
import type { ProfileMetricSummary, T, ToolMetricSummary, UserMetricSummary } from "./types";

const k = "admin_metrics";

export function Panel({ id, title, meta, actions, children }: { id: string; title: string; meta?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="overflow-hidden rounded-3xl border border-border/60 bg-card/40" aria-labelledby={id}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-5 pb-3 pt-4">
        <h2 id={id} className="text-sm font-semibold">
          {title}
        </h2>
        {meta && <span className="text-xs tabular-nums text-muted-foreground">{meta}</span>}
        {actions && <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

export function EmptyRow({ children }: { children: React.ReactNode }) {
  return <p className="border-t border-border/50 px-5 py-10 text-center text-sm text-muted-foreground">{children}</p>;
}

/** The dot carries state, the number carries the value: readable without colour. */
export function Rate({ value, show = true }: { value: number; show?: boolean }) {
  const tone = rateTone(value);
  return (
    <span className="inline-flex items-center gap-1.5 tabular-nums">
      <span className={cn("h-1.5 w-1.5 rounded-full", tone === "ok" ? "bg-success" : tone === "warn" ? "bg-warning" : "bg-destructive")} aria-hidden />
      {show ? `${value}%` : null}
    </span>
  );
}

const th = "px-5 py-2 text-xs font-medium text-muted-foreground";
const td = "px-5 py-3 align-middle";
const num = "text-right tabular-nums";

function Head({ cols }: { cols: { label: string; right?: boolean; className?: string }[] }) {
  return (
    <thead>
      <tr className="border-y border-border/50 text-left">
        {cols.map((c) => (
          <th key={c.label} scope="col" className={cn(th, c.right && "text-right", c.className)}>
            {c.label}
          </th>
        ))}
      </tr>
    </thead>
  );
}

function TokenMix({ prompt, completion, reasoning, fmt }: { prompt: number; completion: number; reasoning: number; fmt: Format }) {
  return (
    <div className="ml-auto flex w-40 flex-col gap-1.5">
      <TokenSplit prompt={prompt} completion={completion} reasoning={reasoning} className="h-1" />
      <span className="text-right text-xs tabular-nums text-muted-foreground">
        {fmt.compact(prompt)} · {fmt.compact(completion)} · {fmt.compact(reasoning)}
      </span>
    </div>
  );
}

export function ProfilesTable({ rows, fmt, range, t }: { rows: ProfileMetricSummary[]; fmt: Format; range: string; t: T }) {
  if (rows.length === 0) return <EmptyRow>{t(`${k}.profiles.empty`, { range })}</EmptyRow>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[44rem] text-sm">
        <Head
          cols={[
            { label: t(`${k}.col.profile`) },
            { label: t(`${k}.col.tokens`), right: true },
            { label: t(`${k}.col.mix`), right: true },
            { label: t(`${k}.col.turns`), right: true },
            { label: t(`${k}.col.tools`), right: true },
            { label: t(`${k}.col.success`), right: true },
            { label: t(`${k}.col.duration`), right: true },
          ]}
        />
        <tbody className="divide-y divide-border/40">
          {rows.map((p) => (
            <tr key={p.profile} className="transition-colors hover:bg-secondary/40">
              <td className={cn(td, "max-w-[16rem] truncate font-medium")}>{p.profile}</td>
              <td className={cn(td, num, "font-medium")}>{fmt.compact(p.total_tokens)}</td>
              <td className={td}>
                <TokenMix prompt={p.prompt_tokens} completion={p.completion_tokens} reasoning={p.reasoning_tokens || 0} fmt={fmt} />
              </td>
              <td className={cn(td, num)}>{fmt.int(p.total_turns)}</td>
              <td className={cn(td, num)}>{fmt.int(p.total_tool_calls)}</td>
              <td className={cn(td, num)}>{p.total_tool_calls > 0 ? <Rate value={p.tool_success_rate} /> : <span className="text-muted-foreground">—</span>}</td>
              <td className={cn(td, num)}>{fmt.seconds(p.avg_turn_duration_seconds)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <TokenLegend t={t} />
    </div>
  );
}

export function TokenLegend({ t }: { t: T }) {
  return (
    <p className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border/50 px-5 py-2.5 text-xs text-muted-foreground">
      <span className="inline-flex items-center gap-1.5">
        <i className="h-1.5 w-3 rounded-full bg-foreground/80" aria-hidden />
        {t(`${k}.summary.input`)}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <i className="h-1.5 w-3 rounded-full bg-primary" aria-hidden />
        {t(`${k}.summary.output`)}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <i className="h-1.5 w-3 rounded-full bg-muted-foreground/45" aria-hidden />
        {t(`${k}.summary.reasoning`)}
      </span>
    </p>
  );
}

export function UsersTable({ rows, fmt, range, t }: { rows: UserMetricSummary[]; fmt: Format; range: string; t: T }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  if (rows.length === 0) return <EmptyRow>{t(`${k}.users.empty`, { range })}</EmptyRow>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[44rem] text-sm">
        <Head
          cols={[
            { label: t(`${k}.col.user`) },
            { label: t(`${k}.col.tokens`), right: true },
            { label: t(`${k}.col.mix`), right: true },
            { label: t(`${k}.col.turns`), right: true },
            { label: t(`${k}.col.tools`), right: true },
            { label: t(`${k}.col.success`), right: true },
            { label: t(`${k}.col.duration`), right: true },
          ]}
        />
        <tbody>
          {rows.map((u) => {
            const expanded = !!open[u.user_id];
            const panelId = `user-${u.user_id.replace(/\W/g, "_")}`;
            return (
              <React.Fragment key={u.user_id}>
                <tr className="border-b border-border/40 transition-colors hover:bg-secondary/40">
                  <td className="px-2 py-1.5">
                    <button
                      type="button"
                      aria-expanded={expanded}
                      aria-controls={panelId}
                      onClick={() => setOpen((o) => ({ ...o, [u.user_id]: !o[u.user_id] }))}
                      className="focus-ring flex w-full items-center gap-2 rounded-xl px-3 py-1.5 text-left"
                    >
                      <ChevronRight className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", expanded && "rotate-90")} aria-hidden />
                      <span className="min-w-0">
                        <span className="block max-w-[14rem] truncate font-medium">{u.user_id}</span>
                        <span className="block text-xs text-muted-foreground">{t(`${k}.users.profiles_n`, { n: u.profile_breakdown.length })}</span>
                      </span>
                    </button>
                  </td>
                  <td className={cn(td, num, "font-medium")}>{fmt.compact(u.total_tokens)}</td>
                  <td className={td}>
                    <TokenMix prompt={u.prompt_tokens} completion={u.completion_tokens} reasoning={u.reasoning_tokens || 0} fmt={fmt} />
                  </td>
                  <td className={cn(td, num)}>{fmt.int(u.total_turns)}</td>
                  <td className={cn(td, num)}>{fmt.int(u.total_tool_calls)}</td>
                  <td className={cn(td, num)}>{u.total_tool_calls > 0 ? <Rate value={u.tool_success_rate} /> : <span className="text-muted-foreground">—</span>}</td>
                  <td className={cn(td, num)}>{fmt.seconds(u.avg_turn_duration_seconds)}</td>
                </tr>
                {expanded && (
                  <tr id={panelId} className="border-b border-border/40 bg-secondary/25">
                    <td colSpan={7} className="px-5 py-4">
                      {u.profile_breakdown.length === 0 ? (
                        <p className="text-sm text-muted-foreground">{t(`${k}.users.no_breakdown`)}</p>
                      ) : (
                        <ul className="divide-y divide-border/40">
                          {u.profile_breakdown.map((pb) => (
                            <li key={pb.profile} className="grid gap-x-6 gap-y-2 py-3 first:pt-0 last:pb-0 md:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
                              <div className="min-w-0">
                                <div className="truncate text-sm font-medium">{pb.profile}</div>
                                <div className="mt-1.5 flex items-center gap-2" title={t(`${k}.users.share`, { n: pb.usage_frequency_percent })}>
                                  <div className="h-1 flex-1 overflow-hidden rounded-full bg-secondary">
                                    <div className="h-full rounded-full bg-foreground/70" style={{ width: `${Math.min(100, Math.max(2, pb.usage_frequency_percent))}%` }} />
                                  </div>
                                  <span className="text-xs tabular-nums text-muted-foreground">{pb.usage_frequency_percent}%</span>
                                </div>
                                <div className="mt-1.5 text-xs tabular-nums text-muted-foreground">
                                  {t(`${k}.users.profile_stats`, { turns: fmt.int(pb.total_turns), tokens: fmt.compact(pb.total_tokens), calls: fmt.int(pb.total_tool_calls) })}
                                </div>
                              </div>
                              <div className="flex flex-wrap content-start gap-1.5">
                                {!pb.tools_breakdown || pb.tools_breakdown.length === 0 ? (
                                  <span className="text-xs text-muted-foreground">{t(`${k}.users.no_tools`)}</span>
                                ) : (
                                  pb.tools_breakdown.map((tb) => (
                                    <span
                                      key={`${tb.mcp_server}/${tb.tool_name}`}
                                      title={t(`${k}.users.tool_title`, { server: tb.mcp_server, calls: tb.call_count, errors: tb.error_count })}
                                      className="inline-flex items-center gap-1.5 rounded-lg border border-border/70 bg-card px-2 py-1 text-xs"
                                    >
                                      <span className="font-mono">{tb.tool_name}</span>
                                      <span className="tabular-nums text-muted-foreground">{tb.call_count}</span>
                                      {tb.error_count > 0 && <span className="font-medium tabular-nums text-destructive">{t(`${k}.users.err`, { n: tb.error_count })}</span>}
                                    </span>
                                  ))
                                )}
                              </div>
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
      <TokenLegend t={t} />
    </div>
  );
}

export function ToolsTable({ rows, fmt, range, t }: { rows: ToolMetricSummary[]; fmt: Format; range: string; t: T }) {
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? rows.filter((r) => r.tool_name.toLowerCase().includes(s) || r.mcp_server.toLowerCase().includes(s)) : rows;
  }, [rows, q]);

  return (
    <Panel
      id="metrics-tools-title"
      title={t(`${k}.tools.title`)}
      meta={q ? t(`${k}.tools.count_filtered`, { shown: shown.length, total: rows.length }) : t(`${k}.tools.count`, { n: rows.length })}
      actions={
        rows.length > 0 ? (
          <div className="w-64 max-w-full">
            <SearchField value={q} onChange={setQ} placeholder={t(`${k}.tools.search`)} />
          </div>
        ) : undefined
      }
    >
      {shown.length === 0 ? (
        <EmptyRow>{q ? t(`${k}.tools.no_match`, { q }) : t(`${k}.tools.empty`, { range })}</EmptyRow>
      ) : (
        <div className="max-h-[26rem] overflow-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <thead className="sticky top-0 z-10 bg-card">
              <tr className="border-y border-border/50 text-left">
                <th scope="col" className={th}>{t(`${k}.col.tool`)}</th>
                <th scope="col" className={th}>{t(`${k}.col.server`)}</th>
                <th scope="col" className={cn(th, "text-right")}>{t(`${k}.col.calls`)}</th>
                <th scope="col" className={cn(th, "text-right")}>{t(`${k}.col.errors`)}</th>
                <th scope="col" className={cn(th, "text-right")}>{t(`${k}.col.success`)}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {shown.map((r) => (
                <tr key={`${r.mcp_server}/${r.tool_name}`} className="transition-colors hover:bg-secondary/40">
                  <td className={cn(td, "max-w-[18rem] truncate font-mono text-[13px] font-medium")}>{r.tool_name}</td>
                  <td className={cn(td, "max-w-[12rem] truncate text-muted-foreground")}>{r.mcp_server}</td>
                  <td className={cn(td, num)}>{fmt.int(r.call_count)}</td>
                  <td className={cn(td, num, r.error_count > 0 ? "font-medium text-destructive" : "text-muted-foreground")}>{fmt.int(r.error_count)}</td>
                  <td className={cn(td, num)}>
                    <Rate value={r.success_rate} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

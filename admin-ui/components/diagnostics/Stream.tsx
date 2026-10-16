"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { AlertCircle, BarChart3, Brain, Check, ChevronRight, Copy, FileCode, FileSpreadsheet, FileText, Loader2, OctagonAlert, Search, Terminal, Wrench, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { getLocale } from "@/lib/i18n/i18n-store";
import { Markdown } from "./Markdown";
import { SessionCharts } from "./Charts";
import { clock, kb } from "./format";
import type { LogEvent, T } from "./types";

const k = "admin_diagnostics.stream";

export function toolIcon(name?: string) {
  const n = (name || "").toLowerCase();
  const cls = "h-3.5 w-3.5 shrink-0 text-muted-foreground";
  if (n.includes("chart")) return <BarChart3 className={cls} aria-hidden />;
  if (n.includes("python") || n.includes("node") || n.includes("code")) return <FileCode className={cls} aria-hidden />;
  if (n.includes("exec") || n.includes("command") || n.includes("terminal")) return <Terminal className={cls} aria-hidden />;
  if (n.includes("search") || n.includes("fetch")) return <Search className={cls} aria-hidden />;
  if (n.includes("excel") || n.includes("xlsx") || n.includes("csv")) return <FileSpreadsheet className={cls} aria-hidden />;
  if (n.includes("pdf") || n.includes("doc") || n.includes("file") || n.includes("ingest")) return <FileText className={cls} aria-hidden />;
  return <Wrench className={cls} aria-hidden />;
}

export function Json({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-muted-foreground">{label}</div>
      <pre className="max-h-52 overflow-auto rounded-xl border border-border bg-muted/50 p-3 font-mono text-xs leading-relaxed">
        {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function Reasoning({ log, t }: { log: LogEvent; t: T }) {
  const [open, setOpen] = useState(true);
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="focus-ring -ml-2 flex items-center gap-2 rounded-lg px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <Brain className="h-3.5 w-3.5" aria-hidden />
        {t(`${k}.reasoning`)}
        <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-90")} aria-hidden />
      </button>
      {open && <p className="mt-1 whitespace-pre-wrap rounded-2xl bg-secondary/50 px-4 py-3 text-xs leading-relaxed text-muted-foreground">{log.content}</p>}
    </div>
  );
}

function ToolCall({ log, t, locale }: { log: LogEvent; t: T; locale: string }) {
  const [open, setOpen] = useState(false);
  const hint = log.params && (log.params.relative_path || log.params.file_name || log.params.command || log.params.title);
  const status =
    log.status === "error" ? (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-warning"><AlertCircle className="h-3.5 w-3.5" aria-hidden />{t(`${k}.tool_error`)}</span>
    ) : log.status === "success" ? (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-success"><Check className="h-3.5 w-3.5" aria-hidden />{t(`${k}.tool_ok`)}</span>
    ) : (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-primary"><Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />{t(`${k}.tool_running`)}</span>
    );
  return (
    <div className="rounded-2xl border border-border/60 bg-card/60">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="focus-ring flex w-full items-center gap-2.5 rounded-2xl px-3.5 py-2.5 text-left transition-colors hover:bg-secondary/50"
      >
        {toolIcon(log.tool)}
        <span className="shrink-0 font-mono text-xs font-medium">{log.tool}</span>
        {hint ? <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">{String(hint)}</span> : <span className="flex-1" />}
        {status}
        <span className="hidden shrink-0 text-xs tabular-nums text-muted-foreground sm:inline">{clock(log.timestamp, locale)}</span>
        <ChevronRight className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} aria-hidden />
        <span className="sr-only">{open ? t(`${k}.collapse`) : t(`${k}.expand`)}</span>
      </button>
      {log.tool === "render_chart" && log.params && (
        <div className="px-3.5 pb-3.5"><SessionCharts charts={[log.params]} /></div>
      )}
      {open && (
        <div className="flex flex-col gap-3 border-t border-border/50 p-3.5">
          {log.params && <Json label={t(`${k}.input`)} value={log.params} />}
          {log.result !== undefined && log.result !== null && <Json label={t(`${k}.output`)} value={log.result as string} />}
        </div>
      )}
    </div>
  );
}

function Complete({ log, t, locale }: { log: LogEvent; t: T; locale: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex flex-col gap-3 border-t border-border/50 pt-4">
      <div className="flex flex-wrap items-center gap-3">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden />
        <span className="min-w-0 flex-1 text-sm font-medium">
          {t(`${k}.completed`, { name: log.test_name || log.test || "" })}
          <span className="ml-2 font-normal tabular-nums text-muted-foreground">
            {t(`${k}.completed_meta`, { seconds: log.duration_sec ?? 0, tools: log.tool_count ?? 0 })}
          </span>
        </span>
        {log.final_output && (
          <button
            type="button"
            onClick={() => {
              navigator.clipboard.writeText(log.final_output || "");
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1600);
            }}
            className="focus-ring inline-flex h-8 items-center gap-1.5 rounded-xl px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            {copied ? <Check className="h-3.5 w-3.5 text-success" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
            {copied ? t(`${k}.copied`) : t(`${k}.copy_response`)}
          </button>
        )}
      </div>
      {log.generated_files && log.generated_files.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {log.generated_files.map((f, i) => (
            <li key={i} className="inline-flex items-center gap-2 rounded-xl border border-border bg-card px-2.5 py-1 text-xs">
              {toolIcon(f.name)}
              <span className="font-medium">{f.name}</span>
              <span className="tabular-nums text-muted-foreground">{kb(f.size_bytes, locale)}</span>
            </li>
          ))}
        </ul>
      )}
      {log.final_output && <Markdown>{log.final_output}</Markdown>}
    </div>
  );
}

export function Stream({ logs, running, autoScroll, t }: { logs: LogEvent[]; running: boolean; autoScroll: boolean; t: T }) {
  const locale = getLocale();
  const scroller = useRef<HTMLDivElement>(null);
  // True while the reader sits at the bottom; scrolling up pauses following until they come back.
  const pinned = useRef(true);

  const toBottom = useCallback(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight; // scrollTop, not scrollIntoView: that would drag the page along too
  }, []);

  const onScroll = useCallback(() => {
    const el = scroller.current;
    if (el) pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  }, []);

  // Layout effect so the jump lands before paint; instant, because smooth scrolling fights the token stream.
  useLayoutEffect(() => {
    if (autoScroll && pinned.current) toBottom();
  }, [logs, autoScroll, toBottom]);

  useEffect(() => {
    if (autoScroll) {
      pinned.current = true;
      toBottom();
    }
  }, [autoScroll, toBottom]);

  const rows: ReactNode[] = [];
  for (const log of logs) {
    if (log.step === "reasoning" && log.content) rows.push(<Reasoning key={log.id} log={log} t={t} />);
    else if (log.step === "tool_call") rows.push(<ToolCall key={log.id} log={log} t={t} locale={locale} />);
    else if (log.step === "token" && log.content && running) rows.push(<Markdown key={log.id}>{log.content}</Markdown>);
    else if (log.step === "test_complete") rows.push(<Complete key={log.id} log={log} t={t} locale={locale} />);
    else if (log.step === "test_error")
      rows.push(
        <div key={log.id} role="alert" className="flex items-start gap-3 rounded-2xl bg-destructive/[0.09] px-4 py-3 dark:bg-destructive/[0.12]">
          <OctagonAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden />
          <div className="min-w-0">
            <div className="text-sm font-medium">{t(`${k}.error_title`)}</div>
            <p className="mt-0.5 break-words font-mono text-xs text-muted-foreground">{String(log.error || log.message)}</p>
          </div>
        </div>,
      );
  }

  return (
    <div className="flex h-[32rem] flex-col overflow-hidden rounded-3xl lg:h-full lg:min-h-0 border border-border/60 bg-card/40">
      <div className="flex items-center gap-3 border-b border-border/50 px-5 py-3">
        <h3 className="text-sm font-semibold">{t(`${k}.title`)}</h3>
        {running && (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-primary">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" aria-hidden />
            {t(`${k}.live`)}
          </span>
        )}
      </div>
      <div ref={scroller} onScroll={onScroll} role="log" aria-label={t(`${k}.title`)} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain p-4 sm:p-5">
        {rows.length === 0 ? (
          <div className="m-auto flex max-w-[40ch] flex-col items-center text-center">
            <Terminal className="mb-4 h-8 w-8 text-muted-foreground" strokeWidth={1.5} aria-hidden />
            <h4 className="text-base font-semibold tracking-[-0.015em]">{t(`${k}.empty_title`)}</h4>
            <p className="mt-1.5 text-sm text-muted-foreground">{t(`${k}.empty_body`)}</p>
          </div>
        ) : (
          rows
        )}
      </div>
    </div>
  );
}

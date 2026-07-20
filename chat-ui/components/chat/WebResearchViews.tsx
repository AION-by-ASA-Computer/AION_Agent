"use client";

import { useMemo, useState } from "react";
import { ChevronDown, Globe, Search } from "lucide-react";
import { formatToolInput, toolInputPreview } from "@/lib/sse/formatToolInput";
import type { ToolStepStatus } from "@/lib/sse/types";
import { cn } from "@/lib/cn";
import type { WebSourceCard } from "@/lib/sse/types";
import { ShimmerText } from "@/components/chat/ShimmerText";
import { useT } from "@/lib/i18n/use-t";

export function webHostLabel(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    return host || url;
  } catch {
    return url;
  }
}

export type ParsedWebSearch = {
  query: string;
  provider?: string;
  error?: string;
  results: Array<{ title: string; url: string; provider?: string }>;
};

export function parseWebSearchOutput(raw: string | undefined | null): ParsedWebSearch | null {
  if (raw == null || !String(raw).trim()) return null;
  try {
    const j = JSON.parse(raw) as Record<string, unknown>;
    const q = typeof j.query === "string" ? j.query : "";
    const err = typeof j.error === "string" ? j.error : undefined;
    const prov =
      typeof j.provider_used === "string"
        ? j.provider_used
        : typeof (j as { provider?: unknown }).provider === "string"
          ? String((j as { provider?: string }).provider)
          : undefined;
    const rows = Array.isArray(j.results) ? j.results : [];
    const results = rows.map((r) => {
      const o = r as Record<string, unknown>;
      return {
        title: String(o.title || o.url || "Fonte"),
        url: String(o.url || "").trim(),
        provider: o.provider != null ? String(o.provider) : undefined,
      };
    });
    return { query: q, provider: prov, error: err, results };
  } catch {
    return null;
  }
}

export type ParsedWebFetch = {
  url: string;
  error?: string;
  mode?: string;
  textLen?: number;
};

export function parseWebFetchOutput(raw: string | undefined | null): ParsedWebFetch | null {
  if (raw == null || !String(raw).trim()) return null;
  try {
    const j = JSON.parse(raw) as Record<string, unknown>;
    return {
      url: String(j.url || ""),
      error: typeof j.error === "string" ? j.error : undefined,
      mode: typeof j.mode === "string" ? j.mode : undefined,
      textLen: typeof j.text === "string" ? j.text.length : undefined,
    };
  } catch {
    return null;
  }
}

function truncate(s: string, n: number): string {
  const t = s.trim();
  if (t.length <= n) return t;
  return `${t.slice(0, n - 1)}…`;
}

export function WebSourcesBar({ cards, messageId }: { cards: WebSourceCard[]; messageId?: string }) {
  if (!cards.length) return null;

  const prefix = messageId ? `source-${messageId}` : "source";

  return (
    <div className="mt-2 mb-1 w-full overflow-hidden">
      <div
        className="no-scrollbar flex items-center gap-2 overflow-x-auto py-1"
        role="list"
        aria-label="Fonti"
        style={{ scrollbarWidth: "none", msOverflowStyle: "none" }}
      >
        <div className="mr-1 flex shrink-0 items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground select-none">
          <Globe className="size-3" aria-hidden />
          <span>Fonti</span>
        </div>
        {cards.map((c) => (
          <a
            key={`${c.index}-${c.url}`}
            id={`${prefix}-${c.index}`}
            href={c.url}
            target="_blank"
            rel="noopener noreferrer"
            role="listitem"
            title={c.title}
            className={cn(
              "group flex shrink-0 items-center gap-1.5 rounded-full border border-border/60 bg-muted/30 px-2.5 py-1 text-xs text-muted-foreground transition-colors",
              "hover:border-primary/25 hover:bg-muted/50 hover:text-foreground",
            )}
          >
            <span className="flex size-4 items-center justify-center rounded-full bg-background text-[8px] font-bold text-muted-foreground group-hover:text-primary">
              {c.index}
            </span>
            <span className="max-w-[140px] truncate font-medium">{webHostLabel(c.url)}</span>
          </a>
        ))}
      </div>
    </div>
  );
}

export type ToolsViewMode = "hidden" | "partial" | "full";

function ToolParamsBlock({ input }: { input: unknown }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const formatted = formatToolInput(input);
  if (!formatted.trim()) return null;
  return (
    <div className="mt-2 border-t border-border/40 pt-1.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-md border border-border/50 bg-muted/30 px-2 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronDown className={cn("size-3 transition-transform duration-200", open && "rotate-180")} />
        <span>{t("chat.tool.params")}</span>
      </button>
      {open ? (
        <pre className="mt-1.5 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-border/50 bg-background/60 p-2 font-mono text-[10px] leading-relaxed text-foreground/90">
          {formatted}
        </pre>
      ) : null}
    </div>
  );
}

function StatusDot({ running, isError }: { running: boolean; isError?: boolean }) {
  return (
    <span
      className={cn(
        "relative flex h-2 w-2 shrink-0 rounded-full",
        running ? "bg-amber-500" : isError ? "bg-destructive" : "bg-emerald-500",
      )}
    >
      {running ? (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
      ) : null}
    </span>
  );
}

function ToolCardShell({
  children,
  isError,
  className,
}: {
  children: React.ReactNode;
  isError?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border/60 bg-muted/20 px-3 py-2.5 text-[12px] shadow-sm",
        isError && "border-destructive/35 bg-destructive/5",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function ToolInvocationCard({
  name,
  input,
  output,
  isError,
  status = "done",
  toolsView,
  tokens_in,
  tokens_out,
}: {
  name: string;
  input?: unknown;
  output?: string | null;
  isError?: boolean;
  status?: ToolStepStatus;
  toolsView: ToolsViewMode;
  tokens_in?: number;
  tokens_out?: number;
}) {
  const t = useT();
  const running = status === "running";
  const ws = useMemo(() => (name === "web_search" ? parseWebSearchOutput(output || "") : null), [name, output]);
  const wf = useMemo(() => (name === "web_fetch_page" ? parseWebFetchOutput(output || "") : null), [name, output]);
  const inputQuery =
    input && typeof input === "object" && "query" in (input as object)
      ? String((input as { query?: unknown }).query ?? "")
      : "";

  const isWeb = name === "web_search" || name === "web_fetch_page";

  if (toolsView === "partial" && isWeb) {
    if (name === "web_search") {
      if (running && !ws) {
        return (
          <ToolCardShell>
            <div className="flex items-center gap-2">
              <StatusDot running />
              <Search className="size-3.5 shrink-0 text-primary/80" aria-hidden />
              <ShimmerText className="text-xs font-medium">{t("chat.tool.web_search_running")}</ShimmerText>
            </div>
            {inputQuery ? (
              <p className="mt-1.5 line-clamp-2 text-[11px] text-muted-foreground italic">
                &ldquo;{truncate(inputQuery, 120)}&rdquo;
              </p>
            ) : null}
          </ToolCardShell>
        );
      }
      if (ws) {
        const n = ws.results.filter((r) => r.url).length;
        const line = ws.error
          ? `${t("chat.tool.result_error")}: ${truncate(ws.error, 80)}`
          : `"${truncate(ws.query || "—", 60)}" · ${n} risultati${ws.provider ? ` (${ws.provider})` : ""}`;
        return (
          <ToolCardShell isError={isError}>
            <div className="flex items-center gap-2 text-muted-foreground">
              <StatusDot running={false} isError={isError} />
              <Search className="size-3.5 shrink-0 text-primary/80" aria-hidden />
              <span className="text-xs font-medium text-foreground">{t("chat.tool.web_search_done")}</span>
              {tokens_in !== undefined && tokens_out !== undefined ? (
                <span className="ml-auto rounded border border-border/50 bg-background/50 px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground">
                  {tokens_in} in / {tokens_out} out
                </span>
              ) : null}
            </div>
            <p className="mt-1.5 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">{line}</p>
          </ToolCardShell>
        );
      }
    }
    if (name === "web_fetch_page") {
      if (running && !wf) {
        return (
          <ToolCardShell>
            <div className="flex items-center gap-2">
              <StatusDot running />
              <Globe className="size-3.5 shrink-0 text-primary/80" aria-hidden />
              <ShimmerText className="text-xs font-medium">{t("chat.tool.web_fetch_running")}</ShimmerText>
            </div>
          </ToolCardShell>
        );
      }
      if (wf) {
        const line = wf.error
          ? `${t("chat.tool.result_error")}: ${truncate(wf.error, 100)}`
          : `${webHostLabel(wf.url || "—")}${wf.textLen != null ? ` · ~${wf.textLen} caratteri` : ""}`;
        return (
          <ToolCardShell isError={isError}>
            <div className="flex items-center gap-2">
              <StatusDot running={false} isError={isError} />
              <Globe className="size-3.5 shrink-0 text-primary/80" aria-hidden />
              <span className="text-xs font-medium text-foreground">{t("chat.tool.web_fetch_done")}</span>
            </div>
            <p className="mt-1.5 line-clamp-2 text-[11px] text-muted-foreground">{line}</p>
          </ToolCardShell>
        );
      }
    }
  }

  if (toolsView === "full" && isWeb) {
    if (name === "web_search" && ws) {
      return (
        <ToolCardShell isError={isError} className="overflow-hidden p-0">
          <div className="flex items-center gap-2 border-b border-border/50 bg-muted/30 px-3.5 py-2.5">
            <StatusDot running={false} isError={isError} />
            <Search className="size-4 shrink-0 text-primary/80" aria-hidden />
            <div className="min-w-0 flex-1">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                {t("chat.tool.web_search_done")}
              </div>
              <div className="mt-0.5 truncate text-[13px] font-medium text-foreground" title={ws.query}>
                {ws.query || "—"}
              </div>
            </div>
            {ws.provider ? (
              <span className="shrink-0 rounded-full border border-border/50 bg-background px-2 py-0.5 text-[9px] font-semibold uppercase text-muted-foreground">
                {ws.provider}
              </span>
            ) : null}
          </div>
          {ws.error ? (
            <div className="px-3.5 py-2.5 text-[11px] font-medium text-destructive">{ws.error}</div>
          ) : (
            <ul className="max-h-52 divide-y divide-border/40 overflow-y-auto px-2 py-2">
              {ws.results
                .filter((r) => r.url)
                .slice(0, 20)
                .map((r, idx) => (
                  <li key={`${r.url}-${idx}`} className="rounded-lg px-2.5 py-2 text-[11px] hover:bg-muted/30">
                    <a
                      href={r.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block font-medium text-primary underline-offset-2 hover:underline"
                    >
                      {truncate(r.title, 120)}
                    </a>
                    <div className="mt-0.5 truncate text-[10px] text-muted-foreground">{r.url}</div>
                  </li>
                ))}
            </ul>
          )}
        </ToolCardShell>
      );
    }
    if (name === "web_fetch_page" && wf) {
      return (
        <ToolCardShell isError={isError}>
          <div className="flex items-center gap-2 border-b border-border/40 pb-2">
            <StatusDot running={false} isError={isError} />
            <Globe className="size-4 shrink-0 text-primary/80" aria-hidden />
            <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              {t("chat.tool.web_fetch_done")}
            </span>
          </div>
          {wf.url ? (
            <a
              href={wf.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 block truncate text-[12px] font-medium text-primary underline-offset-2 hover:underline"
            >
              {wf.url}
            </a>
          ) : null}
          {wf.error ? <p className="mt-1.5 text-[11px] text-destructive">{wf.error}</p> : null}
        </ToolCardShell>
      );
    }
  }

  if (toolsView === "full" && output != null) {
    return (
      <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border border-border/50 bg-background/50 p-2.5 font-mono text-[10px] leading-relaxed text-foreground/90">
        {output}
      </pre>
    );
  }

  return null;
}

export function AssistantToolStepBlock({
  name,
  input,
  output,
  isError,
  status = "done",
  toolsView,
  tokens_in,
  tokens_out,
  masked,
}: {
  name: string;
  input?: unknown;
  output?: string | null;
  isError?: boolean;
  status?: ToolStepStatus;
  toolsView: ToolsViewMode;
  tokens_in?: number;
  tokens_out?: number;
  masked?: string;
}) {
  const t = useT();
  const isWeb = name === "web_search" || name === "web_fetch_page";
  const running = status === "running";
  const preview = toolInputPreview(input);

  const header = (
    <div className="flex items-center gap-2 font-mono text-[10px] font-semibold text-muted-foreground">
      <StatusDot running={running} isError={isError} />
      <span>{name}</span>
      {running ? (
        <ShimmerText className="text-[10px] font-medium">
          {t("chat.tool.running", { name })}
        </ShimmerText>
      ) : tokens_in !== undefined && tokens_out !== undefined ? (
        <span className="ml-auto rounded border border-border/50 bg-background/50 px-1.5 py-0.5 text-[9px] font-medium">
          {tokens_in} in / {tokens_out} out
        </span>
      ) : null}
    </div>
  );

  if (masked === "minimum") {
    return (
      <ToolCardShell isError={isError}>
        {header}
      </ToolCardShell>
    );
  }

  if (toolsView === "partial") {
    if (isWeb) {
      return (
        <ToolInvocationCard
          name={name}
          input={input}
          output={output}
          isError={isError}
          status={status}
          toolsView="partial"
          tokens_in={tokens_in}
          tokens_out={tokens_out}
        />
      );
    }
    return (
      <ToolCardShell>
        {header}
        {preview && running ? (
          <p className="mt-1.5 truncate pl-4 text-[10px] italic text-muted-foreground">&ldquo;{preview}&rdquo;</p>
        ) : null}
      </ToolCardShell>
    );
  }

  if (toolsView === "full") {
    if (isWeb) {
      return (
        <ToolInvocationCard
          name={name}
          input={input}
          output={output}
          isError={isError}
          status={status}
          toolsView="full"
          tokens_in={tokens_in}
          tokens_out={tokens_out}
        />
      );
    }
    return (
      <ToolCardShell>
        {header}
        <ToolParamsBlock input={input} />
        {output != null && output.trim() !== "" ? (
          <div className="mt-2 border-t border-border/40 pt-2">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              {isError ? t("chat.tool.result_error") : t("chat.tool.result")}
            </div>
            <pre
              className={cn(
                "max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border p-2 font-mono text-[10px] leading-relaxed",
                isError
                  ? "border-destructive/25 bg-destructive/5 text-destructive"
                  : "border-border/50 bg-background/50 text-foreground/90",
              )}
            >
              {output}
            </pre>
          </div>
        ) : isError && !running ? (
          <p className="mt-2 pl-4 text-[11px] font-medium text-destructive">{t("chat.tool.result_error")}</p>
        ) : running ? (
          <p className="mt-2 pl-4">
            <ShimmerText className="text-[11px]">{t("chat.tool.waiting")}</ShimmerText>
          </p>
        ) : null}
      </ToolCardShell>
    );
  }

  return null;
}

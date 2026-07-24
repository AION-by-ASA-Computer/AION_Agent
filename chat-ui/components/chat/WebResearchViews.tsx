"use client";

import { useMemo, useState } from "react";
import { ChevronDown, Globe, Search } from "lucide-react";
import { formatToolInput, toolInputPreview } from "@/lib/sse/formatToolInput";
import {
  parseWebFetchOutput,
  parseWebSearchOutput,
  webFetchUrlFromInput,
  webSearchQueryFromInput,
} from "@/lib/sse/webToolParse";
import type { ToolStepStatus } from "@/lib/sse/types";
import { cn } from "@/lib/cn";
import type { WebSourceCard } from "@/lib/sse/types";
import { ShimmerText } from "@/components/chat/ShimmerText";
import { useT } from "@/lib/i18n/use-t";

function webHostLabel(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    return host || url;
  } catch {
    return url;
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
        <div className="mr-1 flex shrink-0 items-center gap-1 text-[0.714em] font-semibold uppercase tracking-wide text-muted-foreground select-none">
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
            <span className="flex size-4 items-center justify-center rounded-full bg-background text-[0.571em] font-bold text-muted-foreground group-hover:text-primary">
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
        className="inline-flex items-center gap-1.5 rounded-md border border-border/50 bg-muted/30 px-2 py-0.5 text-[0.714em] font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronDown className={cn("size-3 transition-transform duration-200", open && "rotate-180")} />
        <span>{t("chat.tool.params")}</span>
      </button>
      {open ? (
        <pre className="mt-1.5 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-border/50 bg-background/60 p-2 font-mono text-[0.714em] leading-relaxed text-foreground/90">
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
        "rounded-xl border border-border/60 bg-muted/20 px-3 py-2.5 text-[0.857em] shadow-sm",
        isError && "border-destructive/35 bg-destructive/5",
        className,
      )}
    >
      {children}
    </div>
  );
}

function ToolInvocationCard({
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
  const inputQuery = webSearchQueryFromInput(input);
  const inputUrl = webFetchUrlFromInput(input);

  const isWeb = name === "web_search" || name === "web_fetch_page";
  const showWebCards = toolsView === "partial" || toolsView === "full";

  if (showWebCards && isWeb) {
    if (name === "web_search") {
      if (running && !ws) {
        const q = inputQuery;
        return (
          <ToolCardShell>
            <div className="flex items-center gap-2">
              <StatusDot running />
              <Search className="size-3.5 shrink-0 text-primary/80" aria-hidden />
              <ShimmerText className="text-xs font-medium">{t("chat.tool.web_search_running")}</ShimmerText>
            </div>
            {q ? (
              <p className="mt-1.5 line-clamp-2 text-[0.786em] text-muted-foreground italic">
                &ldquo;{truncate(q, 120)}&rdquo;
              </p>
            ) : null}
          </ToolCardShell>
        );
      }
      const effective = ws ?? (inputQuery ? { query: inputQuery, results: [], provider: undefined, error: undefined } : null);
      if (effective) {
        if (toolsView === "full" && effective.results.length > 0) {
          return (
            <ToolCardShell isError={isError} className="overflow-hidden p-0">
              <div className="flex items-center gap-2 border-b border-border/50 bg-muted/30 px-3.5 py-2.5">
                <StatusDot running={false} isError={isError} />
                <Search className="size-4 shrink-0 text-primary/80" aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="text-[0.714em] font-semibold uppercase tracking-wide text-muted-foreground">
                    {t("chat.tool.web_search_done")}
                  </div>
                  <div className="mt-0.5 truncate text-[0.929em] font-medium text-foreground" title={effective.query}>
                    {effective.query || "—"}
                  </div>
                </div>
                {effective.provider ? (
                  <span className="shrink-0 rounded-full border border-border/50 bg-background px-2 py-0.5 text-[0.643em] font-semibold uppercase text-muted-foreground">
                    {effective.provider}
                  </span>
                ) : null}
              </div>
              {effective.error ? (
                <div className="px-3.5 py-2.5 text-[0.786em] font-medium text-destructive">{effective.error}</div>
              ) : (
                <ul className="max-h-52 divide-y divide-border/40 overflow-y-auto px-2 py-2">
                  {effective.results
                    .filter((r) => r.url)
                    .slice(0, 20)
                    .map((r, idx) => (
                      <li key={`${r.url}-${idx}`} className="rounded-lg px-2.5 py-2 text-[0.786em] hover:bg-muted/30">
                        <a
                          href={r.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="block font-medium text-primary underline-offset-2 hover:underline"
                        >
                          {truncate(r.title, 120)}
                        </a>
                        <div className="mt-0.5 truncate text-[0.714em] text-muted-foreground">{r.url}</div>
                      </li>
                    ))}
                </ul>
              )}
            </ToolCardShell>
          );
        }
        const n = effective.results.filter((r) => r.url).length;
        const line = effective.error
          ? `${t("chat.tool.result_error")}: ${truncate(effective.error, 80)}`
          : `"${truncate(effective.query || inputQuery || "—", 60)}" · ${n} risultati${effective.provider ? ` (${effective.provider})` : ""}`;
        return (
          <ToolCardShell isError={isError}>
            <div className="flex items-center gap-2 text-muted-foreground">
              <StatusDot running={false} isError={isError} />
              <Search className="size-3.5 shrink-0 text-primary/80" aria-hidden />
              <span className="text-xs font-medium text-foreground">{t("chat.tool.web_search_done")}</span>
              {tokens_in !== undefined && tokens_out !== undefined ? (
                <span className="ml-auto rounded border border-border/50 bg-background/50 px-1.5 py-0.5 text-[0.643em] font-medium text-muted-foreground">
                  {tokens_in} in / {tokens_out} out
                </span>
              ) : null}
            </div>
            <p className="mt-1.5 line-clamp-2 text-[0.786em] leading-relaxed text-muted-foreground">{line}</p>
          </ToolCardShell>
        );
      }
    }
    if (name === "web_fetch_page") {
      if (running && !wf) {
        const u = inputUrl;
        return (
          <ToolCardShell>
            <div className="flex items-center gap-2">
              <StatusDot running />
              <Globe className="size-3.5 shrink-0 text-primary/80" aria-hidden />
              <ShimmerText className="text-xs font-medium">{t("chat.tool.web_fetch_running")}</ShimmerText>
            </div>
            {u ? (
              <p className="mt-1.5 line-clamp-2 text-[0.786em] text-muted-foreground">{truncate(u, 120)}</p>
            ) : null}
          </ToolCardShell>
        );
      }
      const effective = wf ?? (inputUrl ? { url: inputUrl, error: undefined, mode: undefined, textLen: undefined } : null);
      if (effective) {
        if (toolsView === "full") {
          return (
            <ToolCardShell isError={isError}>
              <div className="flex items-center gap-2 border-b border-border/40 pb-2">
                <StatusDot running={false} isError={isError} />
                <Globe className="size-4 shrink-0 text-primary/80" aria-hidden />
                <span className="text-[0.714em] font-semibold uppercase tracking-wide text-muted-foreground">
                  {t("chat.tool.web_fetch_done")}
                </span>
              </div>
              {effective.url ? (
                <a
                  href={effective.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 block truncate text-[0.857em] font-medium text-primary underline-offset-2 hover:underline"
                >
                  {effective.url}
                </a>
              ) : null}
              {effective.error ? <p className="mt-1.5 text-[0.786em] text-destructive">{effective.error}</p> : null}
            </ToolCardShell>
          );
        }
        const line = effective.error
          ? `${t("chat.tool.result_error")}: ${truncate(effective.error, 100)}`
          : `${webHostLabel(effective.url || inputUrl || "—")}${effective.textLen != null ? ` · ~${effective.textLen} caratteri` : ""}`;
        return (
          <ToolCardShell isError={isError}>
            <div className="flex items-center gap-2">
              <StatusDot running={false} isError={isError} />
              <Globe className="size-3.5 shrink-0 text-primary/80" aria-hidden />
              <span className="text-xs font-medium text-foreground">{t("chat.tool.web_fetch_done")}</span>
            </div>
            <p className="mt-1.5 line-clamp-2 text-[0.786em] text-muted-foreground">{line}</p>
          </ToolCardShell>
        );
      }
    }
  }

  if (toolsView === "full" && output != null && !isWeb) {
    return (
      <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border border-border/50 bg-background/50 p-2.5 font-mono text-[0.714em] leading-relaxed text-foreground/90">
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
    <div className="flex items-center gap-2 font-mono text-[0.714em] font-semibold text-muted-foreground">
      <StatusDot running={running} isError={isError} />
      <span>{name}</span>
      {running ? (
        <ShimmerText className="text-[0.714em] font-medium">
          {t("chat.tool.running", { name })}
        </ShimmerText>
      ) : tokens_in !== undefined && tokens_out !== undefined ? (
        <span className="ml-auto rounded border border-border/50 bg-background/50 px-1.5 py-0.5 text-[0.643em] font-medium">
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
          <p className="mt-1.5 truncate pl-4 text-[0.714em] italic text-muted-foreground">&ldquo;{preview}&rdquo;</p>
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
            <div className="mb-1 text-[0.714em] font-semibold uppercase tracking-wide text-muted-foreground">
              {isError ? t("chat.tool.result_error") : t("chat.tool.result")}
            </div>
            <pre
              className={cn(
                "max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border p-2 font-mono text-[0.714em] leading-relaxed",
                isError
                  ? "border-destructive/25 bg-destructive/5 text-destructive"
                  : "border-border/50 bg-background/50 text-foreground/90",
              )}
            >
              {output}
            </pre>
          </div>
        ) : isError && !running ? (
          <p className="mt-2 pl-4 text-[0.786em] font-medium text-destructive">{t("chat.tool.result_error")}</p>
        ) : running ? (
          <p className="mt-2 pl-4">
            <ShimmerText className="text-[0.786em]">{t("chat.tool.waiting")}</ShimmerText>
          </p>
        ) : null}
      </ToolCardShell>
    );
  }

  return null;
}

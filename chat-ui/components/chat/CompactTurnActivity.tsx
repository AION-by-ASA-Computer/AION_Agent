"use client";

import { useMemo, useState } from "react";
import {
  ChevronRight,
  Globe,
  Search,
  Brain,
  Terminal,
  ChevronDown,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { AgentWorkingShimmer } from "@/components/chat/ShimmerText";
import type { TurnSegment, ToolStepStatus } from "@/lib/sse/types";
import {
  parseWebSearchOutput,
  parseWebFetchOutput,
  webSearchQueryFromInput,
  webFetchUrlFromInput,
} from "@/lib/sse/webToolParse";
import { formatToolInput, toolInputPreview } from "@/lib/sse/formatToolInput";

import { SafeErrorBoundary } from "@/components/ui/ErrorBoundary";

function webHostLabel(url?: string | null): string {
  if (!url || typeof url !== "string") return "";
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    return host || url;
  } catch {
    return url || "";
  }
}

function truncate(s: string | null | undefined, n: number): string {
  if (!s || typeof s !== "string") return "";
  const t = s.trim();
  if (t.length <= n) return t;
  return `${t.slice(0, n - 1)}…`;
}

function FaviconImage({ url, className }: { url?: string | null; className?: string }) {
  const [error, setError] = useState(false);
  const host = useMemo(() => {
    if (!url || typeof url !== "string") return "";
    try {
      return new URL(url).hostname;
    } catch {
      return "";
    }
  }, [url]);

  if (error || !host) {
    return <Globe className={cn("size-3.5 shrink-0 text-muted-foreground/70", className)} aria-hidden />;
  }

  return (
    <img
      src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=32`}
      alt=""
      className={cn("size-3.5 shrink-0 rounded-sm object-contain", className)}
      loading="lazy"
      onError={() => setError(true)}
    />
  );
}

type Props = {
  segments: TurnSegment[];
  streaming?: boolean;
  messageId?: string;
  defaultOpen?: boolean;
};

export function CompactTurnActivity(props: Props) {
  return (
    <SafeErrorBoundary
      fallback={
        props.streaming ? (
          <div className="mb-2 select-none">
            <AgentWorkingShimmer />
          </div>
        ) : null
      }
    >
      <CompactTurnActivityInner {...props} />
    </SafeErrorBoundary>
  );
}

function CompactTurnActivityInner({
  segments,
  streaming = false,
  messageId,
  defaultOpen = false,
}: Props) {
  const t = useT();
  const [isOpen, setIsOpen] = useState(defaultOpen);

  // Group and inspect preparatory items
  const {
    webSearches,
    webFetches,
    reasoningSegments,
    otherTools,
    activeRunningStep,
  } = useMemo(() => {
    const webSearches: Array<{
      id: string;
      query: string;
      results: Array<{ title: string; url: string; snippet?: string }>;
      provider?: string;
      error?: string;
      status: ToolStepStatus;
      rawInput: unknown;
      rawOutput?: string;
    }> = [];

    const webFetches: Array<{
      id: string;
      url: string;
      error?: string;
      status: ToolStepStatus;
      rawInput: unknown;
      rawOutput?: string;
    }> = [];

    const reasoningSegments: Array<{
      id: string;
      content: string;
    }> = [];

    const otherTools: Array<{
      id: string;
      name: string;
      input: unknown;
      output?: string;
      error?: string;
      isError?: boolean;
      status: ToolStepStatus;
      tokens_in?: number;
      tokens_out?: number;
    }> = [];

    let activeRunningStep: {
      type: "search" | "fetch" | "reasoning" | "tool";
      name?: string;
      label: string;
    } | null = null;

    for (const seg of segments) {
      if (seg.kind === "reasoning") {
        const trimmed = (seg.content || "").trim();
        if (trimmed) {
          reasoningSegments.push({
            id: seg.id,
            content: trimmed,
          });
        }
      } else if (seg.kind === "status") {
        if (streaming && !activeRunningStep) {
          activeRunningStep = {
            type: "reasoning",
            label: seg.content?.trim() || t("chat.agent_status.thinking"),
          };
        }
      } else if (seg.kind === "generating") {
        if (streaming && !activeRunningStep) {
          activeRunningStep = {
            type: "reasoning",
            label: seg.title?.trim() || t("chat.agent_status.thinking"),
          };
        }
      } else if (seg.kind === "tool") {
        if (seg.name === "thinking") {
          if (seg.status === "running") {
            activeRunningStep = {
              type: "reasoning",
              label: t("chat.agent_status.thinking"),
            };
          }
          continue;
        }

        if (seg.name === "web_search") {
          const ws = parseWebSearchOutput(seg.output || "");
          const inputQ = webSearchQueryFromInput(seg.input);
          const effectiveQ = ws?.query || inputQ || "";
          const effectiveResults = ws?.results?.filter((r) => r && r.url) || [];

          webSearches.push({
            id: seg.id,
            query: effectiveQ,
            results: effectiveResults,
            provider: ws?.provider,
            error: ws?.error || seg.error,
            status: seg.status,
            rawInput: seg.input,
            rawOutput: seg.output,
          });

          if (seg.status === "running") {
            activeRunningStep = {
              type: "search",
              label: t("chat.compact_activity.searching_streaming", {
                query: effectiveQ ? `"${truncate(effectiveQ, 40)}"` : "",
              }),
            };
          }
        } else if (seg.name === "web_fetch_page") {
          const wf = parseWebFetchOutput(seg.output || "");
          const inputU = webFetchUrlFromInput(seg.input);
          const effectiveU = wf?.url || inputU || "";

          webFetches.push({
            id: seg.id,
            url: effectiveU,
            error: wf?.error || seg.error,
            status: seg.status,
            rawInput: seg.input,
            rawOutput: seg.output,
          });

          if (seg.status === "running") {
            activeRunningStep = {
              type: "fetch",
              label: t("chat.compact_activity.reading_page") + (effectiveU ? ` ${webHostLabel(effectiveU)}` : "…"),
            };
          }
        } else {
          otherTools.push({
            id: seg.id,
            name: seg.name,
            input: seg.input,
            output: seg.output,
            error: seg.error,
            isError: seg.isError,
            status: seg.status,
            tokens_in: seg.tokens_in,
            tokens_out: seg.tokens_out,
          });

          if (seg.status === "running") {
            activeRunningStep = {
              type: "tool",
              name: seg.name,
              label: t("chat.compact_activity.running_tool_streaming", { name: seg.name }),
            };
          }
        }
      }
    }

    return {
      webSearches,
      webFetches,
      reasoningSegments,
      otherTools,
      activeRunningStep,
    };
  }, [segments, streaming, t]);

  const totalStepsCount =
    webSearches.length +
    webFetches.length +
    reasoningSegments.length +
    otherTools.length;

  if (totalStepsCount === 0 && !streaming && !activeRunningStep) {
    return null;
  }

  // Generate the main single-line summary header (Claude-style)
  const headerSummary = useMemo(() => {
    if (streaming && activeRunningStep) {
      return {
        prefix: "",
        query: activeRunningStep.label,
        isStreaming: true,
      };
    }

    if (webSearches.length === 1 && webFetches.length === 0 && otherTools.length === 0 && reasoningSegments.length === 0) {
      return {
        prefix: t("chat.compact_activity.searched_web"),
        query: webSearches[0].query ? `${webSearches[0].query}` : "",
        isStreaming: false,
      };
    }

    if (webSearches.length > 0) {
      const mainQ = webSearches[0].query;
      const otherCount = totalStepsCount - 1;
      if (otherCount > 0) {
        return {
          prefix: t("chat.compact_activity.searched_web"),
          query: mainQ ? `${truncate(mainQ, 35)} ${t("chat.compact_activity.and_other_steps", { count: otherCount })}` : t("chat.compact_activity.steps_count", { count: totalStepsCount }),
          isStreaming: false,
        };
      }
      return {
        prefix: t("chat.compact_activity.searched_web"),
        query: mainQ ? `${mainQ}` : "",
        isStreaming: false,
      };
    }

    if (reasoningSegments.length > 0 && totalStepsCount === reasoningSegments.length) {
      return {
        prefix: t("chat.compact_activity.thought_done"),
        query: "",
        isStreaming: false,
      };
    }

    if (otherTools.length === 1 && totalStepsCount === 1) {
      return {
        prefix: t("chat.compact_activity.tool_executed", { name: otherTools[0].name }),
        query: "",
        isStreaming: false,
      };
    }

    return {
      prefix: t("chat.compact_activity.steps_count", { count: totalStepsCount }),
      query: "",
      isStreaming: false,
    };
  }, [streaming, activeRunningStep, webSearches, webFetches, otherTools, reasoningSegments, totalStepsCount, t]);

  return (
    <div className="mb-3 text-sm">
      {/* Compact Header Button */}
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        className={cn(
          "group flex items-center gap-1.5 py-1 px-1.5 -ml-1.5 rounded-lg text-left transition-colors duration-150 select-none",
          "text-muted-foreground hover:text-foreground hover:bg-muted/40",
          isOpen && "text-foreground"
        )}
        aria-expanded={isOpen}
      >
        {headerSummary.isStreaming ? (
          <AgentWorkingShimmer label={headerSummary.query} />
        ) : (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground/90 transition-colors group-hover:text-foreground">
            <span className="font-normal text-muted-foreground">{headerSummary.prefix}</span>
            {headerSummary.query ? (
              <span className="font-medium text-foreground/90">{headerSummary.query}</span>
            ) : null}
            <ChevronRight
              size={13}
              className={cn(
                "shrink-0 opacity-60 transition-transform duration-200 ml-0.5 group-hover:opacity-100",
                isOpen && "rotate-90"
              )}
              aria-hidden
            />
          </div>
        )}
      </button>

      {/* Expanded Accordion Container (Screenshot 2 Style) */}
      <div
        className={cn(
          "grid transition-[grid-template-rows,opacity] duration-200 ease-out",
          isOpen ? "grid-rows-[1fr] opacity-100 mt-2" : "grid-rows-[0fr] opacity-0"
        )}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="rounded-2xl border border-border/50 bg-card/60 dark:bg-[#1c1c1c]/90 p-3.5 shadow-sm space-y-3">
            {/* 1. Web Searches & Results List */}
            {webSearches.map((ws, sIdx) => (
              <div key={ws.id || sIdx} className="space-y-1.5">
                {webSearches.length > 1 || ws.query ? (
                  <div className="flex items-center gap-2 px-1 text-[0.78rem] text-muted-foreground">
                    <Search className="size-3.5 text-primary/70 shrink-0" aria-hidden />
                    <span className="font-medium text-foreground/80 truncate">
                      {ws.query || t("chat.compact_activity.searched_web")}
                    </span>
                    {ws.provider ? (
                      <span className="ml-auto rounded-md border border-border/40 bg-muted/40 px-1.5 py-0.2 text-[0.68rem] text-muted-foreground uppercase">
                        {ws.provider}
                      </span>
                    ) : null}
                  </div>
                ) : null}

                {ws.error ? (
                  <div className="rounded-lg bg-destructive/10 border border-destructive/20 px-3 py-2 text-xs text-destructive">
                    {ws.error}
                  </div>
                ) : null}

                {ws.results.length > 0 ? (
                  <div className="divide-y divide-border/30 rounded-xl border border-border/40 bg-background/50 overflow-hidden">
                    {ws.results.slice(0, 20).map((r, rIdx) => (
                      <a
                        key={`${r.url}-${rIdx}`}
                        href={r.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="group flex items-center justify-between gap-3 px-3 py-2 text-xs transition-colors hover:bg-muted/40"
                      >
                        <div className="flex items-center gap-2.5 min-w-0 flex-1">
                          <FaviconImage url={r.url} />
                          <span className="truncate font-normal text-[0.82rem] text-foreground/90 group-hover:text-primary transition-colors">
                            {r.title || r.url}
                          </span>
                        </div>
                        <span className="shrink-0 text-[0.72rem] text-muted-foreground/80 font-mono">
                          {webHostLabel(r.url)}
                        </span>
                      </a>
                    ))}
                  </div>
                ) : !ws.error && ws.status === "done" ? (
                  <p className="px-2 text-xs text-muted-foreground italic">
                    {t("chat.compact_activity.results_count", { count: 0 })}
                  </p>
                ) : null}
              </div>
            ))}

            {/* 2. Web Page Fetches */}
            {webFetches.map((wf, fIdx) => (
              <div key={wf.id || fIdx} className="rounded-xl border border-border/40 bg-background/40 px-3 py-2 text-xs flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <FaviconImage url={wf.url} />
                  <a
                    href={wf.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="truncate text-primary hover:underline font-medium"
                  >
                    {wf.url}
                  </a>
                </div>
                <span className="shrink-0 text-[0.72rem] text-muted-foreground font-mono">
                  {webHostLabel(wf.url)}
                </span>
              </div>
            ))}

            {/* 3. Reasoning (Thinking) Blocks */}
            {reasoningSegments.map((rs, rIdx) => (
              <CompactReasoningItem key={rs.id || rIdx} content={rs.content} />
            ))}

            {/* 4. Other Tool Invocations */}
            {otherTools.map((tool, tIdx) => (
              <CompactToolItem key={tool.id || tIdx} tool={tool} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function CompactReasoningItem({ content }: { content: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const text = content.trim();
  if (!text) return null;

  return (
    <div className="rounded-xl border border-border/40 bg-background/40 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs font-medium text-foreground/90 transition-colors hover:bg-muted/30"
      >
        <div className="flex items-center gap-2">
          <Brain className="size-3.5 text-primary/80 shrink-0" aria-hidden />
          <span>{t("chat.compact_activity.thought_process")}</span>
        </div>
        <ChevronDown className={cn("size-3.5 text-muted-foreground transition-transform duration-200", open && "rotate-180")} />
      </button>

      {open && (
        <div className="border-t border-border/30 bg-muted/15 p-3">
          <div className="max-h-60 overflow-y-auto whitespace-pre-wrap font-sans text-xs leading-relaxed text-muted-foreground">
            {text}
          </div>
        </div>
      )}
    </div>
  );
}

function CompactToolItem({
  tool,
}: {
  tool: {
    name: string;
    input: unknown;
    output?: string;
    error?: string;
    isError?: boolean;
    status: ToolStepStatus;
    tokens_in?: number;
    tokens_out?: number;
  };
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const preview = toolInputPreview(tool.input);
  const formattedInput = formatToolInput(tool.input);

  return (
    <div className={cn(
      "rounded-xl border border-border/40 bg-background/40 overflow-hidden",
      tool.isError && "border-destructive/30 bg-destructive/5"
    )}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs font-medium text-foreground/90 transition-colors hover:bg-muted/30"
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Terminal className="size-3.5 text-primary/70 shrink-0" aria-hidden />
          <span className="font-mono font-semibold text-xs">{tool.name}</span>
          {preview ? (
            <span className="truncate text-muted-foreground text-[0.75rem] font-normal">
              ({preview})
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {tool.tokens_in !== undefined && tool.tokens_out !== undefined ? (
            <span className="text-[0.65rem] font-mono text-muted-foreground">
              {tool.tokens_in}/{tool.tokens_out} tkn
            </span>
          ) : null}
          <ChevronDown className={cn("size-3.5 text-muted-foreground transition-transform duration-200", open && "rotate-180")} />
        </div>
      </button>

      {open && (
        <div className="border-t border-border/30 bg-muted/15 p-3 space-y-2 text-xs">
          {formattedInput ? (
            <div>
              <div className="text-[0.7rem] uppercase font-semibold text-muted-foreground tracking-wider mb-1">
                {t("chat.tool.params")}
              </div>
              <pre className="max-h-36 overflow-auto whitespace-pre-wrap rounded-lg border border-border/40 bg-background/70 p-2 font-mono text-[0.75rem] text-foreground/90">
                {formattedInput}
              </pre>
            </div>
          ) : null}

          {tool.output ? (
            <div>
              <div className="text-[0.7rem] uppercase font-semibold text-muted-foreground tracking-wider mb-1">
                {t("chat.tool.result")}
              </div>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-border/40 bg-background/70 p-2 font-mono text-[0.75rem] text-foreground/90">
                {tool.output}
              </pre>
            </div>
          ) : tool.error ? (
            <div className="text-destructive text-xs font-medium">
              {tool.error}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

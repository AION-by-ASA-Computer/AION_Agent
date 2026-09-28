"use client";

import { useCallback, useMemo, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  Globe,
  Search,
  Brain,
  Terminal,
  FileText,
  Code2,
  Pencil,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import { AgentWorkingShimmer } from "@/components/chat/ShimmerText";
import { MarkdownCodeBlock } from "@/components/chat/MarkdownCodeBlock";
import type { TurnSegment, ToolStepStatus } from "@/lib/sse/types";
import {
  parseWebSearchOutput,
  parseWebFetchOutput,
  webSearchQueryFromInput,
  webFetchUrlFromInput,
} from "@/lib/sse/webToolParse";
import { formatToolInput, toolInputPreview } from "@/lib/sse/formatToolInput";
import { markdownCodeComponents } from "@/lib/markdown/markdownCodeComponents";
import { artifactLanguage } from "@/lib/artifacts";
import { sessionDownloadUrl } from "@/lib/api/aion";
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

type CompactActivityIconKind = "thinking" | "search" | "read_web" | "run" | "write";

type ActiveRunningStep = { label: string; icon: CompactActivityIconKind };

const ACTIVITY_ICON: Record<CompactActivityIconKind, LucideIcon> = {
  thinking: Brain,
  search: Search,
  read_web: Globe,
  run: Code2,
  write: Pencil,
};

function iconKindForToolName(name: string): CompactActivityIconKind {
  const n = name.toLowerCase();
  if (n === "web_search" || n.includes("search")) return "search";
  if (n === "web_fetch_page" || n.includes("fetch")) return "read_web";
  return "run";
}

function CompactActivityIcon({ kind }: { kind: CompactActivityIconKind }) {
  const Icon = ACTIVITY_ICON[kind];
  return (
    <span
      className="inline-flex size-4 shrink-0 items-center justify-center text-muted-foreground/85"
      aria-hidden
    >
      <Icon className="size-3.5" strokeWidth={2} />
    </span>
  );
}

function StepIcon({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex size-4 shrink-0 items-center justify-center text-muted-foreground/80 [&>svg]:size-3.5">
      {children}
    </span>
  );
}

function CurrentStepRow({ label, icon }: { label: string; icon: CompactActivityIconKind }) {
  return (
    <div className="flex items-center gap-2 text-muted-foreground" role="status" aria-live="polite">
      <CompactActivityIcon kind={icon} />
      <AgentWorkingShimmer label={label} className="min-h-0 py-0" />
    </div>
  );
}

function isExpandableSegment(seg: TurnSegment): boolean {
  if (seg.kind === "reasoning" || seg.kind === "artifact") return true;
  if (seg.kind !== "tool") return false;
  return seg.name !== "web_search" && seg.name !== "web_fetch_page" && seg.name !== "thinking";
}

type Props = {
  segments: TurnSegment[];
  streaming?: boolean;
  messageId?: string;
  defaultOpen?: boolean;
  conversationId?: string;
  token?: string | null;
  isPlanArtifact?: (art: { identifier: string; type?: string; title?: string }, buffer: string) => boolean;
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
  defaultOpen = false,
  conversationId,
  token,
  isPlanArtifact,
}: Props) {
  const t = useT();
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());

  const { visibleSegments, activeRunningStep, webSearches, otherTools, reasoningSegments } = useMemo(() => {
    const visible: TurnSegment[] = [];
    const webSearches: Array<{ query: string }> = [];
    const otherTools: Array<{ name: string }> = [];
    const reasoningSegments: TurnSegment[] = [];
    let activeRunningStep: ActiveRunningStep | null = null;

    for (let segIndex = 0; segIndex < segments.length; segIndex += 1) {
      const seg = segments[segIndex];
      const isLastSegment = segIndex === segments.length - 1;
      if (seg.kind === "reasoning") {
        if (seg.content.trim()) {
          visible.push(seg);
          reasoningSegments.push(seg);
        }
        if (streaming && isLastSegment) {
          activeRunningStep = {
            label: t("chat.compact_activity.thinking_streaming"),
            icon: "thinking",
          };
        }
        continue;
      }
      if (seg.kind === "status") {
        if (streaming && !activeRunningStep) {
          activeRunningStep = {
            label: seg.content?.trim() || t("chat.agent_status.thinking"),
            icon: "thinking",
          };
        }
        if (streaming) visible.push(seg);
        continue;
      }
      if (seg.kind === "generating") {
        if (streaming) {
          visible.push(seg);
          if (!activeRunningStep) {
            activeRunningStep = {
              label: seg.title?.trim()
                ? t("chat.compact_activity.writing_file", { title: seg.title })
                : t("chat.agent_status.thinking"),
              icon: "write",
            };
          }
        }
        continue;
      }
      if (seg.kind === "tool") {
        if (seg.name === "thinking") {
          if (seg.status === "running") {
            activeRunningStep = {
              label: t("chat.agent_status.thinking"),
              icon: "thinking",
            };
          }
          continue;
        }
        visible.push(seg);
        if (seg.name === "web_search") {
          const ws = parseWebSearchOutput(seg.output || "");
          const query = ws?.query || webSearchQueryFromInput(seg.input) || "";
          webSearches.push({ query });
          if (seg.status === "running") {
            activeRunningStep = {
              label: t("chat.compact_activity.searching_streaming", {
                query: query ? `"${truncate(query, 40)}"` : "",
              }),
              icon: "search",
            };
          }
        } else if (seg.name === "web_fetch_page") {
          const wf = parseWebFetchOutput(seg.output || "");
          const url = wf?.url || webFetchUrlFromInput(seg.input) || "";
          if (seg.status === "running") {
            activeRunningStep = {
              label:
                t("chat.compact_activity.reading_page") +
                (url ? ` ${webHostLabel(url)}` : "…"),
              icon: "read_web",
            };
          }
        } else {
          otherTools.push({ name: seg.name });
          if (seg.status === "running") {
            activeRunningStep = {
              label: t("chat.compact_activity.running_tool_streaming", { name: seg.name }),
              icon: iconKindForToolName(seg.name),
            };
          }
        }
        continue;
      }
      if (seg.kind === "text") {
        if (seg.content.trim()) visible.push(seg);
        continue;
      }
      if (seg.kind === "artifact") {
        const planCheck = isPlanArtifact
          ? isPlanArtifact(
              { identifier: seg.id, type: seg.artType, title: seg.title },
              seg.buffer,
            )
          : false;
        if (!planCheck) visible.push(seg);
      }
    }

    if (streaming && !activeRunningStep) {
      const last = segments[segments.length - 1];
      if (last?.kind === "reasoning") {
        activeRunningStep = {
          label: t("chat.compact_activity.thinking_streaming"),
          icon: "thinking",
        };
      } else if (last?.kind === "generating") {
        activeRunningStep = {
          label: last.title?.trim()
            ? t("chat.compact_activity.writing_file", { title: last.title })
            : t("chat.compact_activity.thinking_streaming"),
          icon: "write",
        };
      } else if (last?.kind === "tool" && last.status === "running") {
        if (last.name === "web_search") {
          const query =
            webSearchQueryFromInput(last.input) ||
            parseWebSearchOutput(last.output || "")?.query ||
            "";
          activeRunningStep = {
            label: t("chat.compact_activity.searching_streaming", {
              query: query ? `"${truncate(query, 40)}"` : "",
            }),
            icon: "search",
          };
        } else if (last.name === "web_fetch_page") {
          const url = webFetchUrlFromInput(last.input) || "";
          activeRunningStep = {
            label:
              t("chat.compact_activity.reading_page") +
              (url ? ` ${webHostLabel(url)}` : "…"),
            icon: "read_web",
          };
        } else if (last.name !== "thinking") {
          activeRunningStep = {
            label: t("chat.compact_activity.running_tool_streaming", { name: last.name }),
            icon: iconKindForToolName(last.name),
          };
        } else {
          activeRunningStep = {
            label: t("chat.compact_activity.thinking_streaming"),
            icon: "thinking",
          };
        }
      } else if (last?.kind === "status") {
        activeRunningStep = {
          label: last.content?.trim() || t("chat.compact_activity.thinking_streaming"),
          icon: "thinking",
        };
      }
    }

    return {
      visibleSegments: visible,
      activeRunningStep,
      webSearches,
      otherTools,
      reasoningSegments,
    };
  }, [segments, streaming, t, isPlanArtifact]);

  const totalStepsCount = visibleSegments.length;

  const expandableIds = useMemo(
    () => visibleSegments.filter(isExpandableSegment).map((seg) => seg.id),
    [visibleSegments],
  );

  const allDetailsExpanded =
    expandableIds.length > 0 && expandableIds.every((id) => expandedIds.has(id));

  const toggleDetail = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAllDetails = useCallback(() => {
    setExpandedIds((prev) => {
      const allOpen = expandableIds.length > 0 && expandableIds.every((id) => prev.has(id));
      return allOpen ? new Set() : new Set(expandableIds);
    });
  }, [expandableIds]);

  const currentStepLabel = useMemo(() => {
    if (!streaming) return null;
    if (activeRunningStep?.label) return activeRunningStep.label;
    return t("chat.compact_activity.thinking_streaming");
  }, [streaming, activeRunningStep, t]);

  const currentStepIcon: CompactActivityIconKind = activeRunningStep?.icon ?? "thinking";

  const activeStepShownInExpandedList = useMemo(() => {
    if (!isOpen) return false;
    for (let i = visibleSegments.length - 1; i >= 0; i -= 1) {
      const seg = visibleSegments[i];
      if (seg.kind === "generating") return true;
      if (seg.kind === "status") return true;
      if (seg.kind === "tool" && seg.status === "running") return true;
    }
    return false;
  }, [isOpen, visibleSegments]);

  const showCurrentStepFooter = Boolean(
    streaming &&
      currentStepLabel &&
      totalStepsCount > 0 &&
      (!isOpen || !activeStepShownInExpandedList),
  );

  const headerSummary = useMemo(() => {
    if (
      webSearches.length === 1 &&
      otherTools.length === 0 &&
      reasoningSegments.length === 0 &&
      totalStepsCount === 1
    ) {
      return {
        prefix: t("chat.compact_activity.searched_web"),
        query: webSearches[0].query || "",
        isStreaming: false,
      };
    }

    if (webSearches.length > 0) {
      const mainQ = webSearches[0].query;
      const otherCount = Math.max(0, totalStepsCount - 1);
      if (otherCount > 0) {
        return {
          prefix: t("chat.compact_activity.searched_web"),
          query: mainQ
            ? `${truncate(mainQ, 35)} ${t("chat.compact_activity.and_other_steps", { count: otherCount })}`
            : t("chat.compact_activity.steps_count", { count: totalStepsCount }),
          isStreaming: false,
        };
      }
      return {
        prefix: t("chat.compact_activity.searched_web"),
        query: mainQ || "",
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

    const onlyStep = visibleSegments[0];
    if (visibleSegments.length === 1 && onlyStep?.kind === "artifact") {
      return {
        prefix: t("chat.compact_activity.wrote_file", { title: onlyStep.title || onlyStep.id }),
        query: "",
        isStreaming: false,
      };
    }

    return {
      prefix: t("chat.compact_activity.steps_count", { count: totalStepsCount }),
      query: "",
      isStreaming: false,
    };
  }, [
    webSearches,
    otherTools,
    reasoningSegments,
    totalStepsCount,
    visibleSegments,
    t,
  ]);

  if (totalStepsCount === 0 && !streaming && !currentStepLabel) {
    return null;
  }

  return (
    <div className="mb-2 text-[13px] leading-5">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setIsOpen((prev) => !prev)}
          className={cn(
            "focus-ring group inline-flex min-w-0 max-w-full items-center gap-1 rounded-md py-0.5 pr-1 text-left select-none",
            "text-muted-foreground transition-colors duration-150 hover:text-foreground",
          )}
          aria-expanded={isOpen}
        >
          <span className="min-w-0 truncate">
            {totalStepsCount === 0 && streaming ? (
              <span className="inline-flex items-center gap-1.5">
                <CompactActivityIcon kind={currentStepIcon} />
                <AgentWorkingShimmer label={currentStepLabel!} className="min-h-0 py-0" />
              </span>
            ) : (
              <>
                <span>{headerSummary.prefix}</span>
                {headerSummary.query ? (
                  <span className="text-foreground/80">
                    {headerSummary.prefix ? " " : ""}
                    {headerSummary.query}
                  </span>
                ) : null}
              </>
            )}
          </span>
          <ChevronRight
            size={14}
            className={cn(
              "shrink-0 opacity-50 transition-transform duration-200 group-hover:opacity-80",
              isOpen && "rotate-90",
            )}
            aria-hidden
          />
        </button>
        {isOpen && expandableIds.length > 0 ? (
          <button
            type="button"
            onClick={toggleAllDetails}
            className={cn(
              "focus-ring inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5",
              "text-[12px] text-muted-foreground/80 transition-colors hover:bg-muted/50 hover:text-foreground",
            )}
            aria-pressed={allDetailsExpanded}
          >
            {allDetailsExpanded ? (
              <ChevronsDownUp size={13} aria-hidden />
            ) : (
              <ChevronsUpDown size={13} aria-hidden />
            )}
            <span>
              {allDetailsExpanded
                ? t("chat.compact_activity.collapse_all")
                : t("chat.compact_activity.expand_all")}
            </span>
          </button>
        ) : null}
      </div>

      {showCurrentStepFooter && !isOpen ? (
        <div className="mt-1.5">
          <CurrentStepRow label={currentStepLabel!} icon={currentStepIcon} />
        </div>
      ) : null}

      <div
        className={cn(
          "grid transition-[grid-template-rows,opacity] duration-200 ease-out motion-reduce:transition-none",
          isOpen ? "grid-rows-[1fr] opacity-100 mt-1.5" : "grid-rows-[0fr] opacity-0",
        )}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="ml-1.5 space-y-2.5 border-l border-border/70 pl-4">
            {visibleSegments.map((seg) => {
              if (seg.kind === "reasoning") {
                return (
                  <CompactReasoningItem
                    key={seg.id}
                    content={seg.content}
                    open={expandedIds.has(seg.id)}
                    onToggle={() => toggleDetail(seg.id)}
                  />
                );
              }
              if (seg.kind === "status") {
                return (
                  <div key={seg.id} className="text-[13px] text-muted-foreground">
                    {seg.content}
                  </div>
                );
              }
              if (seg.kind === "generating") {
                return (
                  <div key={seg.id}>
                    <CurrentStepRow
                      icon="write"
                      label={
                        seg.title?.trim()
                          ? t("chat.compact_activity.writing_file", { title: seg.title })
                          : t("chat.agent_status.thinking")
                      }
                    />
                  </div>
                );
              }
              if (seg.kind === "text") {
                return <CompactProcessMarkdown key={seg.id} content={seg.content} />;
              }
              if (seg.kind === "artifact") {
                return (
                  <CompactArtifactItem
                    key={seg.id}
                    title={seg.title || seg.id}
                    language={artifactLanguage(seg.artType, seg.savedPath || "")}
                    code={seg.buffer}
                    savedPath={seg.savedPath}
                    downloadUrl={
                      seg.savedPath && conversationId && token
                        ? sessionDownloadUrl(conversationId, seg.savedPath, token)
                        : undefined
                    }
                    open={expandedIds.has(seg.id)}
                    onToggle={() => toggleDetail(seg.id)}
                  />
                );
              }
              if (seg.kind === "tool") {
                if (seg.name === "web_search") {
                  return <CompactWebSearchItem key={seg.id} seg={seg} />;
                }
                if (seg.name === "web_fetch_page") {
                  return <CompactWebFetchItem key={seg.id} seg={seg} />;
                }
                return (
                  <CompactToolItem
                    key={seg.id}
                    tool={seg}
                    open={expandedIds.has(seg.id)}
                    onToggle={() => toggleDetail(seg.id)}
                  />
                );
              }
              return null;
            })}
            {showCurrentStepFooter && isOpen ? (
              <div className="pt-0.5">
                <CurrentStepRow label={currentStepLabel!} icon={currentStepIcon} />
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function CompactProcessMarkdown({ content }: { content: string }) {
  const components = useMemo(
    () => markdownCodeComponents({ variant: "quiet" }),
    [],
  );
  const text = content.trim();
  if (!text) return null;

  return (
    <div className="prose-chat text-[13px] leading-relaxed text-muted-foreground [&_p]:text-muted-foreground">
      <ReactMarkdown remarkPlugins={[remarkGfm]} disallowedElements={["script"]} unwrapDisallowed components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

function CompactReasoningItem({
  content,
  open,
  onToggle,
}: {
  content: string;
  open: boolean;
  onToggle: () => void;
}) {
  const t = useT();
  const text = content.trim();
  if (!text) return null;
  const long = text.length > 900;

  return (
    <div className="min-w-0">
      <button
        type="button"
        onClick={onToggle}
        className="focus-ring group mb-1 inline-flex items-center gap-2 text-left text-[13px] leading-5 text-muted-foreground transition-colors hover:text-foreground"
        aria-expanded={open}
      >
        <StepIcon>
          <Brain size={14} aria-hidden />
        </StepIcon>
        <span>{t("chat.compact_activity.thought_process")}</span>
        <ChevronRight
          size={13}
          className={cn("opacity-50 transition-transform duration-200", open && "rotate-90")}
          aria-hidden
        />
      </button>
      {open ? (
        <div
          className={cn(
            "whitespace-pre-wrap text-[13px] leading-relaxed text-muted-foreground/90",
            long && "max-h-72 overflow-y-auto pr-1",
          )}
        >
          {text}
        </div>
      ) : null}
    </div>
  );
}

function CompactWebSearchItem({ seg }: { seg: Extract<TurnSegment, { kind: "tool" }> }) {
  const t = useT();
  const ws = parseWebSearchOutput(seg.output || "");
  const query = ws?.query || webSearchQueryFromInput(seg.input) || "";
  const results = ws?.results?.filter((r) => r && r.url) || [];
  const running = seg.status === "running";

  return (
    <div className="min-w-0 space-y-1.5">
      <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
        {running ? (
          <CompactActivityIcon kind="search" />
        ) : (
          <StepIcon>
            <Search size={14} aria-hidden />
          </StepIcon>
        )}
        <div className="min-w-0">
          {running ? (
            <AgentWorkingShimmer
              className="min-h-0 py-0"
              label={t("chat.compact_activity.searching_streaming", {
                query: query ? `"${truncate(query, 40)}"` : "",
              })}
            />
          ) : (
            <>
              <span>{t("chat.compact_activity.searched_web")}</span>
              {query ? <span className="text-foreground/80"> {query}</span> : null}
            </>
          )}
        </div>
      </div>
      {ws?.error ? (
        <p className="pl-6 text-[12px] text-destructive">{ws.error}</p>
      ) : null}
      {results.length > 0 ? (
        <div className="space-y-0.5 pl-6">
          {results.slice(0, 12).map((r, rIdx) => (
            <a
              key={`${r.url}-${rIdx}`}
              href={r.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group flex items-center gap-2 py-0.5 text-[13px] text-foreground/85 transition-colors hover:text-foreground"
            >
              <FaviconImage url={r.url} />
              <span className="min-w-0 flex-1 truncate">{r.title || r.url}</span>
              <span className="shrink-0 text-[11px] text-muted-foreground/75">
                {webHostLabel(r.url)}
              </span>
            </a>
          ))}
        </div>
      ) : seg.status === "done" && !ws?.error ? (
        <p className="pl-6 text-[12px] text-muted-foreground/80">
          {t("chat.compact_activity.results_count", { count: 0 })}
        </p>
      ) : null}
    </div>
  );
}

function CompactWebFetchItem({ seg }: { seg: Extract<TurnSegment, { kind: "tool" }> }) {
  const t = useT();
  const wf = parseWebFetchOutput(seg.output || "");
  const url = wf?.url || webFetchUrlFromInput(seg.input) || "";
  const running = seg.status === "running";

  return (
    <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
      {running ? (
        <CompactActivityIcon kind="read_web" />
      ) : (
        <StepIcon>
          <Globe size={14} aria-hidden />
        </StepIcon>
      )}
      <div className="min-w-0">
        {running ? (
          <AgentWorkingShimmer
            className="min-h-0 py-0"
            label={
              t("chat.compact_activity.reading_page") +
              (url ? ` ${webHostLabel(url)}` : "…")
            }
          />
        ) : (
          <>
            <span>{t("chat.compact_activity.reading_page")}</span>
            {url ? (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-1 text-foreground/80 hover:underline"
              >
                {webHostLabel(url) || url}
              </a>
            ) : null}
          </>
        )}
        {wf?.error ? <p className="text-[12px] text-destructive">{wf.error}</p> : null}
      </div>
    </div>
  );
}

function CompactArtifactItem({
  title,
  language,
  code,
  savedPath,
  downloadUrl,
  open,
  onToggle,
}: {
  title: string;
  language: string;
  code: string;
  savedPath?: string;
  downloadUrl?: string;
  open: boolean;
  onToggle: () => void;
}) {
  const t = useT();

  return (
    <div className="min-w-0">
      <button
        type="button"
        onClick={onToggle}
        className="focus-ring group inline-flex max-w-full items-center gap-2 text-left text-[13px] text-muted-foreground transition-colors hover:text-foreground"
        aria-expanded={open}
      >
        <StepIcon>
          <FileText size={14} aria-hidden />
        </StepIcon>
        <span className="min-w-0 truncate">
          {t("chat.compact_activity.wrote_file", { title })}
        </span>
        <ChevronRight
          size={13}
          className={cn("shrink-0 opacity-50 transition-transform duration-200", open && "rotate-90")}
          aria-hidden
        />
      </button>
      {open ? (
        <div className="pl-6 pt-1">
          {downloadUrl ? (
            <a
              href={downloadUrl}
              target="_blank"
              rel="noreferrer"
              className="mb-1 inline-block text-[12px] text-muted-foreground hover:text-foreground hover:underline"
            >
              {savedPath || title}
            </a>
          ) : null}
          {code.trim() ? (
            <MarkdownCodeBlock language={language} code={code} variant="quiet" />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function CompactToolItem({
  tool,
  open,
  onToggle,
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
  open: boolean;
  onToggle: () => void;
}) {
  const t = useT();
  const preview = toolInputPreview(tool.input);
  const formattedInput = formatToolInput(tool.input);
  const running = tool.status === "running";

  return (
    <div className="min-w-0">
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          "focus-ring group inline-flex max-w-full items-center gap-2 text-left text-[13px] transition-colors",
          tool.isError ? "text-destructive" : "text-muted-foreground hover:text-foreground",
        )}
        aria-expanded={open}
      >
        {running ? (
          <CompactActivityIcon kind={iconKindForToolName(tool.name)} />
        ) : (
          <StepIcon>
            <Terminal size={14} aria-hidden />
          </StepIcon>
        )}
        <span className="min-w-0 truncate">
          {running ? (
            <AgentWorkingShimmer
              className="min-h-0 py-0"
              label={t("chat.compact_activity.running_tool_streaming", { name: tool.name })}
            />
          ) : (
            <>
              {t("chat.compact_activity.tool_executed", { name: tool.name })}
              {preview ? (
                <span className="font-normal text-muted-foreground/80"> {preview}</span>
              ) : null}
            </>
          )}
        </span>
        <ChevronRight
          size={13}
          className={cn("shrink-0 opacity-50 transition-transform duration-200", open && "rotate-90")}
          aria-hidden
        />
      </button>

      {open ? (
        <div className="space-y-2 pl-6 pt-1.5 text-[12px]">
          {formattedInput ? (
            <div>
              <div className="mb-1 text-[11px] text-muted-foreground">{t("chat.tool.params")}</div>
              <pre className="max-h-36 overflow-auto whitespace-pre-wrap rounded-lg bg-muted/40 p-2 font-mono text-[12px] text-foreground/85">
                {formattedInput}
              </pre>
            </div>
          ) : null}
          {tool.output ? (
            <div>
              <div className="mb-1 text-[11px] text-muted-foreground">{t("chat.tool.result")}</div>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-muted/40 p-2 font-mono text-[12px] text-foreground/85">
                {tool.output}
              </pre>
            </div>
          ) : tool.error ? (
            <div className="text-destructive">{tool.error}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

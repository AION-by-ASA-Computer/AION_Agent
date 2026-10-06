"use client";

import React, { useMemo } from "react";
import {
  CheckCircle2,
  Circle,
  Loader2,
  Search,
  FileCode,
  Terminal,
  Wrench,
  XCircle,
  Clock,
  Sparkles,
  Layers,
} from "lucide-react";
import type { PlanExecutionActivity } from "@/lib/api/plan-execution";
import { cn } from "@/lib/cn";

function formatTime(ts?: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

interface ProcessedActivity {
  id: string;
  title: string;
  detail?: string;
  type: "search" | "file" | "command" | "turn" | "tool";
  status: "running" | "done" | "error";
  ts?: number;
  duration?: number;
}

function getIcon(type: ProcessedActivity["type"], status: ProcessedActivity["status"], isLatest: boolean) {
  if (status === "error") {
    return <XCircle className="size-4 text-destructive shrink-0" />;
  }
  if (status === "running" || (isLatest && status !== "done")) {
    return <Loader2 className="size-4 text-orange-500 animate-spin shrink-0" />;
  }
  if (status === "done") {
    return <CheckCircle2 className="size-4 text-emerald-500 shrink-0" />;
  }

  switch (type) {
    case "search":
      return <Search className="size-3.5 text-blue-500 shrink-0" />;
    case "file":
      return <FileCode className="size-3.5 text-amber-500 shrink-0" />;
    case "command":
      return <Terminal className="size-3.5 text-purple-500 shrink-0" />;
    case "turn":
      return <Sparkles className="size-3.5 text-orange-500 shrink-0" />;
    default:
      return <Wrench className="size-3.5 text-muted-foreground shrink-0" />;
  }
}

function processActivities(raw: PlanExecutionActivity[], running: boolean): ProcessedActivity[] {
  const list: ProcessedActivity[] = [];
  const toolCallsMap = new Map<string, ProcessedActivity>();

  raw.forEach((act, idx) => {
    const rawLabel = (act.label || act.message || act.phase || "").trim();
    if (!rawLabel) return;

    // Ignore pure noisy duplicates like "Web search - done" if we already have the search query item
    const isDoneEvent = /—\s*done$/i.test(rawLabel) || act.status === "done";
    const cleanLabel = rawLabel.replace(/\s*—\s*done$/i, "").trim();

    // Check category
    let type: ProcessedActivity["type"] = "tool";
    let title = "Operazione";
    let detail: string | undefined = undefined;

    if (/^web\s*search:/i.test(cleanLabel) || act.tool_name === "web_search") {
      type = "search";
      title = "Ricerca Web";
      detail = cleanLabel.replace(/^web\s*search:\s*/i, "").trim();
    } else if (/^searching\s*codebase:/i.test(cleanLabel) || /^grep\s*search:/i.test(cleanLabel)) {
      type = "search";
      title = "Scansione Codice";
      detail = cleanLabel.replace(/^(?:searching\s*codebase|grep\s*search):\s*/i, "").trim();
    } else if (/^operazione\s*sandbox:/i.test(cleanLabel) || /^(?:read|write|replace)_file/i.test(act.tool_name || "")) {
      type = "file";
      title = "File Workspace";
      detail = cleanLabel.replace(/^operazione\s*sandbox:\s*/i, "").trim();
    } else if (/^task\s*`[^`]+`\s*—\s*turno/i.test(cleanLabel) || /^starting\s*plan/i.test(cleanLabel)) {
      type = "turn";
      title = cleanLabel;
    } else if (/^run_command|bash|exec/i.test(act.tool_name || "") || /^executing/i.test(cleanLabel)) {
      type = "command";
      title = "Esecuzione Comando";
      detail = cleanLabel;
    } else {
      title = cleanLabel;
    }

    const key = `${type}-${detail || title}`;

    if (isDoneEvent) {
      const existing = toolCallsMap.get(key);
      if (existing) {
        existing.status = "done";
        if (act.ts && existing.ts) {
          existing.duration = Math.max(1, act.ts - existing.ts);
        }
        return;
      }
    }

    const item: ProcessedActivity = {
      id: `${act.ts || idx}-${key}`,
      title,
      detail: detail && detail !== title ? detail : undefined,
      type,
      status: act.status === "error" ? "error" : isDoneEvent ? "done" : "running",
      ts: act.ts,
    };

    toolCallsMap.set(key, item);
    list.push(item);
  });

  // If main plan is not running anymore, mark all un-errored items as done
  if (!running) {
    list.forEach((item) => {
      if (item.status === "running") item.status = "done";
    });
  }

  return list;
}

export function TaskActivityFeed({
  activities,
  running,
}: {
  activities: PlanExecutionActivity[];
  running: boolean;
}) {
  const processed = useMemo(() => processActivities(activities, running), [activities, running]);

  if (!processed.length) {
    return (
      <div className="flex flex-col items-center justify-center p-8 text-center rounded-2xl border border-dashed border-border/70 bg-card/30">
        {running ? (
          <div className="flex items-center gap-2.5 text-xs text-orange-600 dark:text-orange-400 font-medium">
            <Loader2 className="size-4 animate-spin text-orange-500" />
            <span>Inizializzazione delle operazioni in corso…</span>
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">Nessuna operazione registrata per questa task.</span>
        )}
      </div>
    );
  }

  return (
    <div className="relative pl-3 space-y-2.5 before:absolute before:left-5 before:top-2 before:bottom-2 before:w-0.5 before:bg-border/60">
      {processed.map((item, idx) => {
        const isLatest = idx === processed.length - 1 && running;

        return (
          <div
            key={item.id}
            className={cn(
              "relative flex items-start gap-3 rounded-xl p-2.5 text-xs transition-all duration-150 animate-in fade-in-0 duration-200",
              item.status === "running"
                ? "bg-orange-500/10 border border-orange-500/30 text-foreground font-medium shadow-xs"
                : item.status === "error"
                ? "bg-destructive/10 border border-destructive/25 text-destructive font-medium"
                : "bg-card/60 hover:bg-card border border-black/[0.05] dark:border-white/[0.06] text-muted-foreground hover:text-foreground"
            )}
          >
            {/* Left Status Icon */}
            <div className="relative z-10 flex size-5 shrink-0 items-center justify-center rounded-full bg-background border border-border/80 shadow-2xs mt-0.5">
              {getIcon(item.type, item.status, isLatest)}
            </div>

            {/* Content info */}
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <span className={cn("font-semibold", item.status === "running" ? "text-orange-600 dark:text-orange-400" : "text-foreground")}>
                  {item.title}
                </span>

                <div className="flex items-center gap-1.5 shrink-0">
                  {item.duration ? (
                    <span className="font-mono text-[10px] text-muted-foreground/80 flex items-center gap-0.5">
                      <Clock size={10} />
                      {item.duration}s
                    </span>
                  ) : item.ts ? (
                    <span className="font-mono text-[10px] text-muted-foreground/60">{formatTime(item.ts)}</span>
                  ) : null}

                  <span
                    className={cn(
                      "text-[9.5px] font-bold uppercase tracking-wider px-1.5 py-0.2 rounded-full",
                      item.status === "running"
                        ? "bg-orange-500/20 text-orange-600 dark:text-orange-400 animate-pulse"
                        : item.status === "error"
                        ? "bg-destructive/20 text-destructive"
                        : "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                    )}
                  >
                    {item.status === "running" ? "in corso" : item.status === "error" ? "errore" : "completato"}
                  </span>
                </div>
              </div>

              {item.detail ? (
                <p className="mt-1 font-mono text-[11px] leading-relaxed text-muted-foreground/90 bg-muted/40 p-1.5 rounded-lg border border-black/[0.03] dark:border-white/[0.03] break-all">
                  {item.detail}
                </p>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

"use client";

import { CheckCircle2, Circle, Loader2, Wrench, XCircle } from "lucide-react";
import type { PlanExecutionActivity } from "@/lib/api/plan-execution";
import { cn } from "@/lib/cn";

function formatTime(ts?: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function activityIcon(act: PlanExecutionActivity, isLatest: boolean) {
  if (act.phase === "tool") {
    if (act.status === "error") {
      return <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />;
    }
    if (act.status === "done") {
      return <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500/90" />;
    }
    if (isLatest) {
      return <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-primary" />;
    }
    return <Wrench className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
  }
  if (isLatest) {
    return <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-primary" />;
  }
  return <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />;
}

export function TaskActivityFeed({
  activities,
  running,
}: {
  activities: PlanExecutionActivity[];
  running: boolean;
}) {
  const visible = activities.slice(-40);
  const show = [...visible].reverse();

  if (!show.length) {
    return (
      <div className="rounded-xl border border-dashed border-border/70 bg-muted/20 px-4 py-8 text-center text-sm text-muted-foreground">
        {running ? (
          <span className="inline-flex items-center justify-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            Avvio operazioni…
          </span>
        ) : (
          "Nessuna attività registrata per questa task."
        )}
      </div>
    );
  }

  return (
    <ol className="space-y-2" aria-live="polite" aria-busy={running}>
      {show.map((act, idx) => {
        const label = act.label || act.message || act.phase || "…";
        const isLatest = idx === 0 && running;
        return (
          <li
            key={`${act.ts ?? idx}-${act.phase}-${act.tool_name || ""}-${label.slice(0, 48)}`}
            className={cn(
              "flex gap-2.5 rounded-lg border px-3 py-2.5 text-[13px] leading-snug",
              isLatest
                ? "border-primary/30 bg-primary/5 text-foreground"
                : "border-border/50 bg-background/60 text-muted-foreground",
            )}
          >
            {activityIcon(act, isLatest)}
            <span className="min-w-0 flex-1">
              <span className="block">{label}</span>
              {act.ts ? (
                <span className="mt-0.5 block text-[10px] opacity-60">{formatTime(act.ts)}</span>
              ) : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

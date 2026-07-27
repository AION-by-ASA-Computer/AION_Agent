"use client";

import { useMemo } from "react";
import type { ContextBudgetState } from "@/lib/sse/types";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

const PART_COLORS: Record<string, string> = {
  system_prompt: "bg-slate-500",
  tool_specs: "bg-zinc-500",
  skills: "bg-violet-500",
  web_tools: "bg-sky-500",
  tool_results: "bg-amber-500",
  user: "bg-blue-500",
  assistant: "bg-emerald-500",
  reasoning: "bg-purple-500",
  compaction: "bg-orange-500",
  memory_injections: "bg-pink-500",
  system_messages: "bg-neutral-500",
  other: "bg-stone-400",
};

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function partLabel(t: (key: string, vars?: Record<string, string | number>) => string, key: string): string {
  const path = `chat.context_budget.parts.${key}`;
  const label = t(path);
  return label === path ? key : label;
}

function gaugeStrokeClass(pct: number, triggerPct: number): string {
  if (pct >= triggerPct) return "stroke-destructive";
  if (pct >= triggerPct * 0.85) return "stroke-amber-500";
  return "stroke-emerald-500";
}

type GaugeProps = {
  pct: number;
  triggerPct: number;
  active?: boolean;
  unavailable?: boolean;
  onClick: () => void;
  className?: string;
};

export function ContextBudgetGauge({
  pct,
  triggerPct,
  active,
  unavailable,
  onClick,
  className,
}: GaugeProps) {
  const t = useT();
  const clamped = Math.min(100, Math.max(0, pct));
  const size = 28;
  const stroke = 2.5;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - clamped / 100);
  const strokeClass = unavailable
    ? "stroke-muted-foreground/35"
    : gaugeStrokeClass(clamped, triggerPct);

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "focus-ring inline-flex size-7 shrink-0 items-center justify-center rounded-full border transition-colors",
        active
          ? "border-primary/45 bg-primary/10"
          : "border-border/80 bg-muted/25 hover:bg-muted/45",
        className,
      )}
      aria-label={
        unavailable
          ? t("chat.context_budget.gauge_idle")
          : t("chat.context_budget.gauge_aria", { pct: clamped.toFixed(0) })
      }
      aria-expanded={active}
      title={
        unavailable
          ? t("chat.context_budget.gauge_idle")
          : t("chat.context_budget.gauge_aria", { pct: clamped.toFixed(0) })
      }
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="-rotate-90"
        aria-hidden
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          className="stroke-muted-foreground/30"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          className={cn(strokeClass, "transition-[stroke-dashoffset] duration-300")}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={unavailable ? circumference : offset}
        />
      </svg>
    </button>
  );
}

type DetailsProps = {
  budget: ContextBudgetState;
  className?: string;
};

export function ContextBudgetBar({ budget, className }: DetailsProps) {
  const t = useT();
  const pct = Math.min(100, Math.max(0, budget.pct));
  const triggerPct =
    budget.maxPrompt > 0 ? Math.min(100, (budget.trigger / budget.maxPrompt) * 100) : 0;

  const parts = useMemo(
    () => [...budget.parts].sort((a, b) => b.tokens - a.tokens),
    [budget.parts],
  );

  return (
    <div
      className={cn(
        "rounded-xl border border-border/60 bg-muted/30 px-3 py-2.5 text-[0.786em]",
        className,
      )}
      role="status"
      aria-label={t("chat.context_budget.aria", { pct: pct.toFixed(0) })}
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="font-medium text-foreground">{t("chat.context_budget.title")}</span>
        <span className="tabular-nums text-muted-foreground">
          {formatTokens(budget.total)} / {formatTokens(budget.maxPrompt)} tok
          <span className="ml-1.5 font-semibold text-foreground">{pct.toFixed(0)}%</span>
        </span>
      </div>

      <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-background/80 ring-1 ring-border/40">
        {triggerPct > 0 && triggerPct < 100 ? (
          <div
            className="pointer-events-none absolute inset-y-0 z-10 w-px bg-destructive/70"
            style={{ left: `${triggerPct}%` }}
            title={t("chat.context_budget.trigger", {
              pct: triggerPct.toFixed(0),
            })}
          />
        ) : null}
        <div className="flex h-full min-w-0">
          {parts.map((part) => {
            const width = budget.maxPrompt > 0 ? (part.tokens / budget.maxPrompt) * 100 : 0;
            if (width <= 0) return null;
            const label = partLabel(t, part.key);
            return (
              <div
                key={part.key}
                className={cn("h-full shrink-0", PART_COLORS[part.key] || PART_COLORS.other)}
                style={{ width: `${width}%` }}
                title={`${label}: ${formatTokens(part.tokens)} (${part.pct.toFixed(1)}%)`}
              />
            );
          })}
        </div>
      </div>

      <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[0.929em] text-muted-foreground">
        {parts.slice(0, 8).map((part) => (
          <li key={part.key} className="inline-flex items-center gap-1">
            <span
              className={cn(
                "inline-block size-2 rounded-sm",
                PART_COLORS[part.key] || PART_COLORS.other,
              )}
              aria-hidden
            />
            <span>{partLabel(t, part.key)}</span>
            <span className="tabular-nums text-foreground/80">{part.pct.toFixed(0)}%</span>
          </li>
        ))}
        {budget.messageCount > 0 ? (
          <li className="text-muted-foreground/80">
            {t("chat.context_budget.messages", { count: budget.messageCount })}
          </li>
        ) : null}
      </ul>
    </div>
  );
}

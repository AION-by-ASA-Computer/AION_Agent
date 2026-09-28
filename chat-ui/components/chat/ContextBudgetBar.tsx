"use client";

import { useMemo, useState } from "react";
import { BookOpen, CheckCircle2, Circle, XCircle, Zap, ChevronDown } from "lucide-react";
import type { ContextBudgetState } from "@/lib/sse/types";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import type { UsedTool } from "@/components/layout/CapabilitiesChip";
import type { SkillStatus } from "@/components/chat/ChatWorkspace";

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

function formatSlug(slug: string): string {
  return slug
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

const SKILL_STATE_CONFIG = {
  loaded: {
    icon: CheckCircle2,
    iconClass: "text-emerald-500",
    badgeClass: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
    badgeKey: "chat.capabilities.skill_loaded",
  },
  failed: {
    icon: XCircle,
    iconClass: "text-rose-500",
    badgeClass: "bg-rose-500/15 text-rose-600 dark:text-rose-400",
    badgeKey: "chat.capabilities.skill_failed",
  },
  pending: {
    icon: Circle,
    iconClass: "text-muted-foreground/40",
    badgeClass: "bg-muted/60 text-muted-foreground/60",
    badgeKey: "chat.capabilities.skill_pending",
  },
} as const;

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
  usedTools: UsedTool[];
  skillStatuses: SkillStatus[];
  className?: string;
};

export function ContextBudgetBar({ budget, usedTools, skillStatuses, className }: DetailsProps) {
  const t = useT();
  const pct = Math.min(100, Math.max(0, budget.pct));
  const triggerPct =
    budget.maxPrompt > 0 ? Math.min(100, (budget.trigger / budget.maxPrompt) * 100) : 0;

  const [toolsOpen, setToolsOpen] = useState(false);
  const [skillsOpen, setSkillsOpen] = useState(false);

  const parts = useMemo(
    () => [...budget.parts].sort((a, b) => b.tokens - a.tokens),
    [budget.parts],
  );

  const totalTools = usedTools.length;
  const loadedCount = skillStatuses.filter((s) => s.loadState === "loaded").length;
  const failedCount = skillStatuses.filter((s) => s.loadState === "failed").length;

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

      {(totalTools > 0 || skillStatuses.length > 0) && (
        <div className="mt-3 border-t border-border/40 pt-2 flex flex-col gap-2">
          {/* ── Section: Tools actually used ── */}
          {totalTools > 0 && (
            <div className="rounded-lg border border-border/40 bg-muted/10 overflow-hidden">
              <button
                type="button"
                className="w-full flex items-center justify-between px-2.5 py-1.5 hover:bg-muted/40 transition-colors"
                onClick={() => setToolsOpen(!toolsOpen)}
              >
                <div className="flex items-center gap-1.5">
                  <Zap size={11} className="text-violet-500 shrink-0" aria-hidden />
                  <span className="text-[0.714em] font-bold uppercase tracking-wider text-violet-500">
                    {t("chat.capabilities.tools_used")}
                  </span>
                  <span className="rounded-full bg-violet-500/15 px-1.5 py-0.5 text-[0.65em] font-bold tabular-nums text-violet-500">
                    {totalTools}
                  </span>
                </div>
                <ChevronDown size={12} className={cn("text-muted-foreground transition-transform duration-200", toolsOpen && "rotate-180")} aria-hidden />
              </button>

              {toolsOpen && (
                <div className="px-2 pb-2 pt-1 border-t border-border/40">
                  <ul className="space-y-0.5">
                    {usedTools.map((tool) => (
                      <li
                        key={tool.name}
                        className="flex items-center justify-between rounded-lg px-1.5 py-1 hover:bg-muted/40 transition-colors"
                      >
                        <div className="flex items-center gap-1.5 min-w-0">
                          {tool.hasError ? (
                            <XCircle size={13} className="shrink-0 text-rose-500" aria-hidden />
                          ) : (
                            <CheckCircle2 size={13} className="shrink-0 text-emerald-500" aria-hidden />
                          )}
                          <span className="truncate text-[0.786em] font-medium text-foreground">
                            {formatSlug(tool.name)}
                          </span>
                        </div>
                        {tool.callCount > 1 && (
                          <span className="ml-2 shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[0.65em] font-mono tabular-nums text-muted-foreground">
                            ×{tool.callCount}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* ── Section: Skills with load state ── */}
          {skillStatuses.length > 0 && (
            <div className="rounded-lg border border-border/40 bg-muted/10 overflow-hidden">
              <button
                type="button"
                className="w-full flex items-center justify-between px-2.5 py-1.5 hover:bg-muted/40 transition-colors"
                onClick={() => setSkillsOpen(!skillsOpen)}
              >
                <div className="flex items-center gap-1.5">
                  <BookOpen size={11} className="text-amber-500 shrink-0" aria-hidden />
                  <span className="text-[0.714em] font-bold uppercase tracking-wider text-amber-500">
                    {t("chat.capabilities.skills")}
                  </span>
                </div>
                <ChevronDown size={12} className={cn("text-muted-foreground transition-transform duration-200", skillsOpen && "rotate-180")} aria-hidden />
              </button>

              {skillsOpen && (
                <div className="px-2 pb-2 pt-1 border-t border-border/40">
                  <ul className="space-y-0.5">
                    {skillStatuses.map((skill) => {
                      const cfg = SKILL_STATE_CONFIG[skill.loadState];
                      const Icon = cfg.icon;
                      return (
                        <li
                          key={skill.name}
                          className="flex items-center justify-between rounded-lg px-1.5 py-1 hover:bg-muted/40 transition-colors"
                        >
                          <div className="flex items-center gap-1.5 min-w-0">
                            <Icon size={13} className={cn("shrink-0", cfg.iconClass)} aria-hidden />
                            <span
                              className={cn(
                                "truncate text-[0.786em] font-medium",
                                skill.loadState === "pending"
                                  ? "text-muted-foreground"
                                  : "text-foreground",
                              )}
                            >
                              {formatSlug(skill.name)}
                            </span>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* ── Footer ── */}
          {totalTools > 0 && (
            <p className="px-1 py-1 text-[0.68em] text-muted-foreground/50 select-none">
              {t("chat.capabilities.realtime_hint")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

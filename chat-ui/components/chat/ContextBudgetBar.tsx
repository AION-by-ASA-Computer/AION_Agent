"use client";

/**
 * Conversation-memory indicator for the composer: a quiet ring (gauge) plus a
 * plain-language popover. The ring stays neutral until the conversation is
 * genuinely filling up; technical breakdowns (token parts, tools, skills) live
 * behind a "Details" disclosure so non-technical users see only the headline.
 */

import { useMemo, useState } from "react";
import { BookOpen, CheckCircle2, Circle, XCircle, Zap, ChevronDown, ChevronRight } from "lucide-react";
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

const SKILL_STATE_ICON = {
  loaded: CheckCircle2,
  failed: XCircle,
  pending: Circle,
} as const;

/** i18n keys for the per-skill state label (used / failed). */
const SKILL_STATE_LABEL = {
  loaded: "chat.capabilities.skill_loaded",
  failed: "chat.capabilities.skill_failed",
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

/** Severity tier shared by ring and panel: calm until ~70%, warn near the compaction trigger. */
type Tier = "ok" | "filling" | "full";
function budgetTier(pct: number, triggerPct: number): Tier {
  if (pct >= triggerPct) return "full";
  if (pct >= Math.min(70, triggerPct * 0.85)) return "filling";
  return "ok";
}

const TIER_STROKE: Record<Tier, string> = {
  ok: "stroke-foreground/40",
  filling: "stroke-amber-500",
  full: "stroke-destructive",
};
const TIER_BAR: Record<Tier, string> = {
  ok: "bg-primary/70",
  filling: "bg-amber-500",
  full: "bg-destructive",
};

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
  // Thin 18px ring inside a 28px hit target: present but not competing with the send button.
  const size = 18;
  const stroke = 2;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - clamped / 100);
  const tier = budgetTier(clamped, triggerPct);
  const label = unavailable
    ? t("chat.context_budget.gauge_idle")
    : t("chat.context_budget.gauge_aria", { pct: clamped.toFixed(0) });

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "focus-ring inline-flex size-7 shrink-0 items-center justify-center rounded-full transition-colors",
        active ? "bg-muted/70" : "hover:bg-muted/50",
        // Calm tiers fade back so the ring only draws the eye when it matters.
        tier === "ok" && !active && "opacity-60 hover:opacity-100",
        className,
      )}
      aria-label={label}
      aria-expanded={active}
      title={label}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          className="stroke-foreground/15"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          className={cn(
            unavailable ? "stroke-transparent" : TIER_STROKE[tier],
            "transition-[stroke-dashoffset,stroke] duration-500 ease-out",
          )}
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
  usedTools?: UsedTool[];
  skillStatuses?: SkillStatus[];
  className?: string;
};

export function ContextBudgetBar({
  budget,
  usedTools = [],
  skillStatuses = [],
  className,
}: DetailsProps) {
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
  // All available skills are listed; those never loaded this turn were simply not needed, so they
  // are shown dimmed (no state label) and sorted after the used ones.
  const loadedCount = skillStatuses.filter((s) => s.loadState === "loaded").length;
  const sortedSkills = [...skillStatuses].sort(
    (x, y) => Number(y.loadState !== "pending") - Number(x.loadState !== "pending"),
  );

  const tier = budgetTier(pct, triggerPct || 92);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const hasExtras = totalTools > 0 || skillStatuses.length > 0;

  return (
    <div
      className={cn(
        "rounded-2xl border border-border/60 bg-card px-4 py-3.5 text-[0.857em] shadow-[0_6px_24px_-8px_rgb(0_0_0/0.18)]",
        className,
      )}
      role="status"
      aria-label={t("chat.context_budget.aria", { pct: pct.toFixed(0) })}
    >
      {/* Headline: plain-language status first, number second. */}
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-semibold text-foreground">{t(`chat.context_budget.status_${tier}`)}</span>
        <span className="tabular-nums text-muted-foreground">{pct.toFixed(0)}%</span>
      </div>
      <p className="mt-0.5 text-muted-foreground">{t(`chat.context_budget.hint_${tier}`)}</p>

      {/* One calm bar; per-part colours are reserved for the details view. */}
      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-foreground/10">
        <div
          className={cn("h-full rounded-full transition-[width] duration-500 ease-out", TIER_BAR[tier])}
          style={{ width: `${pct}%` }}
        />
      </div>

      {parts.length > 0 || hasExtras ? (
        <button
          type="button"
          onClick={() => setDetailsOpen((v) => !v)}
          aria-expanded={detailsOpen}
          className="focus-ring mt-3 inline-flex items-center gap-1 rounded-md text-muted-foreground transition-colors hover:text-foreground"
        >
          {detailsOpen ? t("chat.context_budget.details_hide") : t("chat.context_budget.details_show")}
          <ChevronDown
            size={12}
            className={cn("transition-transform duration-200", detailsOpen && "rotate-180")}
            aria-hidden
          />
        </button>
      ) : null}

      {detailsOpen ? (
        <div className="mt-3 border-t border-border/50 pt-3">
          <div className="mb-2 flex items-center justify-between tabular-nums text-muted-foreground">
            <span>
              {formatTokens(budget.total)} / {formatTokens(budget.maxPrompt)} tok
            </span>
            {budget.messageCount > 0 ? (
              <span>{t("chat.context_budget.messages", { count: budget.messageCount })}</span>
            ) : null}
          </div>
          {/* One segmented bar (each segment = share of the whole window) + a dot legend that
              names the segments; the tick marks where auto-summarization kicks in. */}
          <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-foreground/10">
            <div className="flex h-full min-w-0 gap-px">
              {parts.map((part) => {
                const width = budget.maxPrompt > 0 ? (part.tokens / budget.maxPrompt) * 100 : 0;
                if (width <= 0) return null;
                return (
                  <div
                    key={part.key}
                    className={cn("h-full shrink-0 opacity-85", PART_COLORS[part.key] || PART_COLORS.other)}
                    style={{ width: `${width}%` }}
                    title={`${partLabel(t, part.key)}: ${formatTokens(part.tokens)} tok`}
                  />
                );
              })}
            </div>
            {triggerPct > 0 && triggerPct < 100 ? (
              <div
                className="pointer-events-none absolute inset-y-0 z-10 w-px bg-foreground/50"
                style={{ left: `${triggerPct}%` }}
                title={t("chat.context_budget.trigger", { pct: triggerPct.toFixed(0) })}
              />
            ) : null}
          </div>
          <ul className="mt-3 grid grid-cols-2 gap-x-5 gap-y-1.5">
            {parts.slice(0, 8).map((part) => (
              <li key={part.key} className="flex min-w-0 items-center gap-2 text-xs">
                <span
                  className={cn("size-2 shrink-0 rounded-full", PART_COLORS[part.key] || PART_COLORS.other)}
                  aria-hidden
                />
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{partLabel(t, part.key)}</span>
                <span className="tabular-nums text-foreground/80">
                  {part.pct < 1 ? "<1" : part.pct.toFixed(0)}%
                </span>
              </li>
            ))}
          </ul>

      {hasExtras && (
        <div className="mt-3 flex flex-col gap-0.5 border-t border-border/50 pt-2">
          {/* Tools actually used: same disclosure-row idiom as ReasoningDisclosure. */}
          {totalTools > 0 && (
            <div>
              <button
                type="button"
                className="focus-ring flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
                aria-expanded={toolsOpen}
                onClick={() => setToolsOpen(!toolsOpen)}
              >
                <span className="flex size-5 shrink-0 items-center justify-center rounded-md bg-violet-500/12 text-violet-500"><Zap size={12} aria-hidden /></span>
                <span className="text-xs font-medium">{t("chat.capabilities.tools_used")}</span>
                <span className="rounded-full bg-muted/60 px-1.5 text-[0.786em] tabular-nums">{totalTools}</span>
                <ChevronRight
                  size={14}
                  className={cn("ml-auto shrink-0 opacity-70 transition-transform duration-200", toolsOpen && "rotate-90")}
                  aria-hidden
                />
              </button>
              {toolsOpen && (
                <ul className="mt-1 rounded-lg bg-muted/35 px-2 py-1.5">
                  {usedTools.map((tool) => (
                    <li key={tool.name} className="flex items-center gap-2 px-1 py-1">
                      {tool.hasError ? (
                        <XCircle size={13} className="shrink-0 text-destructive" aria-hidden />
                      ) : (
                        <CheckCircle2 size={13} className="shrink-0 text-emerald-500" aria-hidden />
                      )}
                      <span className="min-w-0 flex-1 truncate text-xs text-foreground/90">
                        {formatSlug(tool.name)}
                      </span>
                      {tool.callCount > 1 && (
                        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">×{tool.callCount}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* Skills with load state. */}
          {skillStatuses.length > 0 && (
            <div>
              <button
                type="button"
                className="focus-ring flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
                aria-expanded={skillsOpen}
                onClick={() => setSkillsOpen(!skillsOpen)}
              >
                <span className="flex size-5 shrink-0 items-center justify-center rounded-md bg-amber-500/12 text-amber-600 dark:text-amber-400"><BookOpen size={12} aria-hidden /></span>
                <span className="text-xs font-medium">{t("chat.capabilities.skills")}</span>
                <span className="rounded-full bg-muted/60 px-1.5 text-[0.786em] tabular-nums">
                  {loadedCount}/{skillStatuses.length}
                </span>
                <ChevronRight
                  size={14}
                  className={cn("ml-auto shrink-0 opacity-70 transition-transform duration-200", skillsOpen && "rotate-90")}
                  aria-hidden
                />
              </button>
              {skillsOpen && (
                <ul className="mt-1 rounded-lg bg-muted/35 px-2 py-1.5">
                  {sortedSkills.map((skill) => {
                    const Icon = SKILL_STATE_ICON[skill.loadState];
                    return (
                      <li key={skill.name} className="flex items-center gap-2 px-1 py-1">
                        <Icon
                          size={13}
                          className={cn(
                            "shrink-0",
                            skill.loadState === "loaded" && "text-emerald-500",
                            skill.loadState === "failed" && "text-destructive",
                            skill.loadState === "pending" && "text-muted-foreground/35",
                          )}
                          aria-hidden
                        />
                        <span
                          className={cn(
                            "min-w-0 flex-1 truncate text-xs",
                            skill.loadState === "pending" ? "text-muted-foreground/70" : "text-foreground/90",
                          )}
                        >
                          {formatSlug(skill.name)}
                        </span>
                        {skill.loadState !== "pending" && (
                          <span
                            className={cn(
                              "shrink-0 text-xs",
                              skill.loadState === "loaded" && "text-emerald-600 dark:text-emerald-400",
                              skill.loadState === "failed" && "text-destructive",
                            )}
                          >
                            {t(SKILL_STATE_LABEL[skill.loadState])}
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
        </div>
      ) : null}
    </div>
  );
}

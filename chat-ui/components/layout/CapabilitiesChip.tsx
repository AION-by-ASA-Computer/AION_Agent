"use client";

import { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  CheckCircle2,
  ChevronDown,
  Circle,
  Wrench,
  XCircle,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import type { SkillStatus } from "@/components/chat/ChatWorkspace";

export type UsedTool = {
  name: string;
  callCount: number;
  hasError: boolean;
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

export function CapabilitiesChip({
  usedTools,
  skillStatuses,
}: {
  usedTools: UsedTool[];
  skillStatuses: SkillStatus[];
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const totalTools = usedTools.length;
  const hasAny = totalTools > 0 || skillStatuses.length > 0;

  // Conta skill per stato per il badge del trigger
  const loadedCount = skillStatuses.filter((s) => s.loadState === "loaded").length;
  const failedCount = skillStatuses.filter((s) => s.loadState === "failed").length;

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!hasAny) return null;

  const hasToolErrors = usedTools.some((t) => t.hasError);
  const hasSkillErrors = failedCount > 0;
  const hasErrors = hasToolErrors || hasSkillErrors;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        id="capabilities-chip-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="true"
        className={cn(
          "focus-ring inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[0.786em] font-semibold transition-all duration-200 hover:scale-[1.01] active:scale-[0.99]",
          open
            ? "border-primary/40 bg-primary/10 text-primary"
            : hasErrors
              ? "border-rose-500/40 bg-rose-500/10 text-rose-500 hover:bg-rose-500/15"
              : "border-border/80 bg-muted/20 text-muted-foreground hover:bg-muted/40 hover:text-foreground",
        )}
        title={t("chat.capabilities.label")}
      >
        <Wrench size={12} className="shrink-0" aria-hidden />
        {totalTools > 0 && (
          <span className="tabular-nums">{totalTools}</span>
        )}
        <ChevronDown
          size={10}
          className={cn(
            "shrink-0 opacity-70 transition-transform duration-150",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>

      {open && (
        <div
          role="dialog"
          aria-label={t("chat.capabilities.label")}
          className={cn(
            "absolute left-0 top-full z-50 mt-2 w-[min(100vw-2rem,17rem)] rounded-xl border border-border bg-card/95 shadow-xl backdrop-blur-md",
            "animate-in fade-in-0 slide-in-from-top-2 duration-150",
          )}
        >
          {/* ── Section: Tools actually used ── */}
          <div className="px-3 pt-3 pb-1">
            <div className="mb-1.5 flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <Zap size={11} className="text-violet-500 shrink-0" aria-hidden />
                <span className="text-[0.714em] font-bold uppercase tracking-wider text-violet-500">
                  {t("chat.capabilities.tools_used")}
                </span>
              </div>
              {totalTools > 0 && (
                <span className="rounded-full bg-violet-500/15 px-1.5 py-0.5 text-[0.65em] font-bold tabular-nums text-violet-500">
                  {totalTools}
                </span>
              )}
            </div>

            {totalTools === 0 ? (
              <p className="py-1.5 text-[0.75em] text-muted-foreground/70 italic">
                {t("chat.capabilities.no_tools")}
              </p>
            ) : (
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
            )}
          </div>

          <div className="my-1.5 border-t border-border/40" />

          {/* ── Section: Skills with load state ── */}
          <div className="px-3 pb-3 pt-1">
            <div className="mb-1.5 flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <BookOpen size={11} className="text-amber-500 shrink-0" aria-hidden />
                <span className="text-[0.714em] font-bold uppercase tracking-wider text-amber-500">
                  {t("chat.capabilities.skills")}
                </span>
              </div>
              {skillStatuses.length > 0 && (
                <div className="flex items-center gap-1">
                  {loadedCount > 0 && (
                    <span className="rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[0.65em] font-bold tabular-nums text-emerald-600 dark:text-emerald-400">
                      {loadedCount}✓
                    </span>
                  )}
                  {failedCount > 0 && (
                    <span className="rounded-full bg-rose-500/15 px-1.5 py-0.5 text-[0.65em] font-bold tabular-nums text-rose-600 dark:text-rose-400">
                      {failedCount}✗
                    </span>
                  )}
                </div>
              )}
            </div>

            {skillStatuses.length === 0 ? (
              <p className="py-1.5 text-[0.75em] text-muted-foreground/70 italic">
                {t("chat.capabilities.no_skills")}
              </p>
            ) : (
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
                      <span
                        className={cn(
                          "ml-2 shrink-0 rounded-full px-1.5 py-0.5 text-[0.65em] font-medium",
                          cfg.badgeClass,
                        )}
                      >
                        {t(cfg.badgeKey)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {/* ── Footer ── */}
          {totalTools > 0 && (
            <>
              <div className="border-t border-border/40" />
              <p className="px-3 py-2 text-[0.68em] text-muted-foreground/50 select-none">
                {t("chat.capabilities.realtime_hint")}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

"use client";

import { useEffect, useRef } from "react";
import {
  BookOpen,
  Bug,
  ChevronDown,
  HelpCircle,
  MessageSquare,
  Sparkles,
} from "lucide-react";

import { ComposerOptionRow } from "@/components/chat/ComposerOptionRow";
import type { AgentMode } from "@/components/layout/ChatHeader";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

const MODE_META: Record<
  AgentMode,
  { labelKey: string; descKey: string; icon: typeof MessageSquare; soon?: boolean; beta?: boolean }
> = {
  normal: {
    labelKey: "chat.agent_mode.normal",
    descKey: "chat.agent_mode.normal_desc",
    icon: MessageSquare,
  },
  plan: {
    labelKey: "chat.agent_mode.plan",
    descKey: "chat.agent_mode.plan_desc",
    icon: Sparkles,
  },
  deep_research: {
    labelKey: "chat.agent_mode.deep_research",
    descKey: "chat.agent_mode.deep_research_desc",
    icon: BookOpen,
  },
  ask: {
    labelKey: "chat.agent_mode.ask",
    descKey: "chat.agent_mode.ask_desc",
    icon: HelpCircle,
    soon: true,
  },
  debug: {
    labelKey: "chat.agent_mode.debug",
    descKey: "chat.agent_mode.debug_desc",
    icon: Bug,
    soon: true,
  },
};

export function AgentModeSelectChip({
  mode,
  onChange,
  open,
  onOpenChange,
  onAfterSelect,
}: {
  mode: AgentMode;
  onChange: (mode: AgentMode) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAfterSelect?: (mode: AgentMode) => void;
}) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);
  const meta = MODE_META[mode];
  const Icon = meta.icon;

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onOpenChange(false);
    };
    window.addEventListener("mousedown", onDoc);
    return () => window.removeEventListener("mousedown", onDoc);
  }, [open, onOpenChange]);

  const chipClass =
    mode === "plan"
      ? "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400 hover:bg-amber-500/20 shadow-[0_0_12px_rgba(245,158,11,0.15)] font-semibold"
      : mode === "deep_research"
        ? "border-violet-500/40 bg-violet-500/10 text-violet-600 dark:text-violet-400 hover:bg-violet-500/20 shadow-[0_0_12px_rgba(139,92,246,0.15)] font-semibold"
        : open
          ? "border-primary/40 bg-primary/10 text-primary shadow-xs font-semibold"
          : "border-black/[0.08] dark:border-white/[0.08] bg-card/70 dark:bg-card/40 text-foreground hover:bg-card/95 dark:hover:bg-card/70 hover:border-black/15 dark:hover:border-white/15 font-semibold";

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        className={cn(
          "focus-ring inline-flex h-7 max-w-[10rem] items-center gap-1.5 rounded-full border px-3 text-xs shadow-2xs backdrop-blur-xl transition-all duration-200 hover:scale-[1.02] active:scale-[0.98] sm:max-w-[12rem]",
          chipClass,
        )}
      >
        <Icon size={12} className={cn("shrink-0", mode === "normal" && "text-primary")} aria-hidden />
        <span className="truncate">{t(meta.labelKey)}</span>
        <ChevronDown size={10} className="shrink-0 opacity-60" aria-hidden />
      </button>

      {open ? (
        <div className="absolute bottom-full left-0 z-50 mb-2 w-[min(100vw-2rem,18rem)] rounded-2xl border border-black/10 bg-card/90 p-2 text-card-foreground shadow-2xl backdrop-blur-2xl animate-in fade-in-0 zoom-in-95 slide-in-from-bottom-2 duration-200 dark:border-white/10 dark:bg-card/85">
          <div className="border-b border-border/40 pb-1.5 px-2 text-[0.714em] font-bold uppercase tracking-wider text-muted-foreground">
            {t("chat.agent_mode.select")}
          </div>
          <div className="max-h-64 overflow-y-auto p-0.5 custom-scrollbar">
            {(Object.keys(MODE_META) as AgentMode[]).map((key) => {
              const m = MODE_META[key];
              const ModeIcon = m.icon;
              return (
                <ComposerOptionRow
                  key={key}
                  label={t(m.labelKey)}
                  description={t(m.descKey)}
                  selected={mode === key}
                  disabled={m.soon}
                  badge={
                    m.beta
                      ? t("chat.agent_mode.beta")
                      : m.soon
                        ? t("chat.agent_mode.soon")
                        : undefined
                  }
                  badgeTone={m.beta ? "beta" : "muted"}
                  icon={<ModeIcon size={13} className="shrink-0 opacity-80" />}
                  onClick={() => {
                    if (m.soon) return;
                    onChange(key);
                    onAfterSelect?.(key);
                    onOpenChange(false);
                  }}
                />
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

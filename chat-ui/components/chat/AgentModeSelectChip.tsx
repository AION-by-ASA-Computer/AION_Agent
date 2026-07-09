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
  { labelKey: string; descKey: string; icon: typeof MessageSquare; soon?: boolean }
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
      ? "border-orange-500/40 bg-orange-500/10 text-orange-500"
      : mode === "deep_research"
        ? "border-violet-500/40 bg-violet-500/10 text-violet-500"
        : open || mode !== "normal"
          ? "border-primary/40 bg-primary/10 text-primary"
          : "border-border/80 bg-muted/20 text-muted-foreground hover:bg-muted/40 hover:text-foreground";

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        className={cn(
          "focus-ring inline-flex h-8 max-w-[10.5rem] items-center gap-1.5 rounded-full border px-3 text-[11px] font-semibold transition-all duration-200 hover:scale-[1.01] active:scale-[0.99] sm:max-w-[12rem]",
          chipClass,
        )}
      >
        <Icon size={12} className="shrink-0" aria-hidden />
        <span className="truncate">{t(meta.labelKey)}</span>
        <ChevronDown size={10} className="shrink-0 opacity-70" aria-hidden />
      </button>

      {open ? (
        <div className="absolute bottom-full left-0 z-50 mb-2 w-[min(100vw-2rem,17rem)] rounded-xl border border-border bg-card/95 p-1 shadow-lg backdrop-blur-md animate-in fade-in-0 slide-in-from-bottom-2 duration-150">
          <div className="border-b border-border/45 px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            {t("chat.agent_mode.select")}
          </div>
          <div className="max-h-64 overflow-y-auto p-0.5">
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
                  badge={m.soon ? t("chat.agent_mode.soon") : undefined}
                  icon={<ModeIcon size={12} className="shrink-0 opacity-80" />}
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

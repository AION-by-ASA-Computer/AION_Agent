"use client";

import { useEffect, useRef } from "react";
import { ChevronDown, Globe, GlobeLock } from "lucide-react";

import { ComposerOptionRow } from "@/components/chat/ComposerOptionRow";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

export function WebSearchChip({
  enabled,
  onChange,
  open,
  onOpenChange,
}: {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onOpenChange(false);
    };
    window.addEventListener("mousedown", onDoc);
    return () => window.removeEventListener("mousedown", onDoc);
  }, [open, onOpenChange]);

  const Icon = enabled ? Globe : GlobeLock;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        className={cn(
          "focus-ring inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[11px] font-semibold transition-all duration-200 hover:scale-[1.01] active:scale-[0.99]",
          open || enabled
            ? "border-cyan-500/35 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300"
            : "border-border/80 bg-muted/20 text-muted-foreground hover:bg-muted/40 hover:text-foreground",
        )}
        title={t("chat.web_search.global")}
      >
        <Icon size={12} className="shrink-0" aria-hidden />
        <span>{enabled ? t("chat.web_search.on_short") : t("chat.web_search.off_short")}</span>
        <ChevronDown size={10} className="shrink-0 opacity-70" aria-hidden />
      </button>

      {open ? (
        <div className="absolute bottom-full left-0 z-50 mb-2 w-[min(100vw-2rem,15rem)] rounded-xl border border-border bg-card/95 p-1 shadow-lg backdrop-blur-md animate-in fade-in-0 slide-in-from-bottom-2 duration-150">
          <div className="border-b border-border/45 px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            {t("chat.web_search.global")}
          </div>
          <div className="p-0.5">
            <ComposerOptionRow
              label={t("chat.web_search.off_short")}
              description={t("chat.web_search.off_desc")}
              selected={!enabled}
              icon={<GlobeLock size={12} className="shrink-0 opacity-80" />}
              onClick={() => {
                onChange(false);
                onOpenChange(false);
              }}
            />
            <ComposerOptionRow
              label={t("chat.web_search.on_short")}
              description={t("chat.web_search.on_desc")}
              selected={enabled}
              icon={<Globe size={12} className="shrink-0 opacity-80" />}
              onClick={() => {
                onChange(true);
                onOpenChange(false);
              }}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

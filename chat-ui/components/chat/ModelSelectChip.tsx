"use client";

import { useEffect, useRef } from "react";
import { Check, ChevronDown, Loader2, Sparkles } from "lucide-react";

import { ComposerOptionRow } from "@/components/chat/ComposerOptionRow";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";

export type LlmProviderOption = {
  slug: string;
  display_name: string;
  description?: string;
  is_default?: boolean;
};

export function ModelSelectChip({
  providers,
  selectedSlug,
  loading,
  open,
  onOpenChange,
  onSelect,
  placement = "above",
}: {
  providers: LlmProviderOption[];
  selectedSlug: string | null;
  loading?: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (slug: string | null) => void;
  /** Dropdown opens above the chip (composer) or below (header). */
  placement?: "above" | "below";
}) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);
  const selected = providers.find((p) => p.slug === selectedSlug);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onOpenChange(false);
    };
    window.addEventListener("mousedown", onDoc);
    return () => window.removeEventListener("mousedown", onDoc);
  }, [open, onOpenChange]);

  if (!providers.length && !loading) return null;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        className={cn(
          "focus-ring inline-flex h-7 max-w-[10rem] items-center gap-1.5 rounded-full px-2.5 text-xs font-semibold transition-all duration-200 hover:scale-[1.01] active:scale-[0.99] sm:max-w-[12rem]",
          open || selectedSlug
            ? "bg-primary/10 text-primary"
            : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
        )}
        title={t("chat.model.select")}
      >
        {loading ? (
          <Loader2 size={12} className="shrink-0 animate-spin" aria-hidden />
        ) : (
          <Sparkles size={12} className="shrink-0 text-primary/80" aria-hidden />
        )}
        <span className="truncate">
          {selected?.display_name || t("chat.model.label")}
        </span>
        <ChevronDown size={10} className="shrink-0 opacity-60" aria-hidden />
      </button>

      {open ? (
        <div
          className={cn(
            "absolute left-0 z-50 w-[min(100vw-2rem,17rem)] rounded-2xl border border-border bg-card p-1.5 shadow-2xl animate-in fade-in-0 zoom-in-95 duration-200",
            placement === "below"
              ? "top-full mt-2 slide-in-from-top-2"
              : "bottom-full mb-2 slide-in-from-bottom-2",
          )}
        >
          <div className="border-b border-border/40 px-2.5 py-1.5 text-[0.714em] font-bold uppercase tracking-wider text-muted-foreground">
            {t("chat.model.select")}
          </div>
          <div className="max-h-56 overflow-y-auto p-0.5 custom-scrollbar">
            {loading ? (
              <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
                <Loader2 size={12} className="animate-spin" />
                {t("integrationsPage.loading")}
              </div>
            ) : (
              providers.map((provider) => (
                <ComposerOptionRow
                  key={provider.slug}
                  label={provider.display_name}
                  description={
                    provider.description ||
                    (provider.is_default ? t("chat.model.default_hint") : undefined)
                  }
                  selected={provider.slug === selectedSlug}
                  onClick={() => {
                    onSelect(provider.slug === selectedSlug ? null : provider.slug);
                    onOpenChange(false);
                  }}
                />
              ))
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

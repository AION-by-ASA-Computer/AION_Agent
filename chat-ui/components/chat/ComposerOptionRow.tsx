"use client";

import { Check } from "lucide-react";

import { cn } from "@/lib/cn";

export function ComposerOptionRow({
  label,
  description,
  selected,
  disabled,
  badge,
  badgeTone = "muted",
  icon,
  showRadio,
  trailing,
  onClick,
}: {
  label: string;
  description?: string;
  selected?: boolean;
  disabled?: boolean;
  badge?: string;
  badgeTone?: "muted" | "beta";
  icon?: React.ReactNode;
  showRadio?: boolean;
  trailing?: React.ReactNode;
  onClick?: () => void;
}) {
  const badgeEl = badge ? (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 text-[0.643em] font-semibold",
        badgeTone === "beta"
          ? "border border-amber-500/40 bg-amber-500/15 text-amber-700 dark:text-amber-300"
          : "border border-border/60 bg-muted/40 text-muted-foreground",
      )}
    >
      {badge}
    </span>
  ) : null;

  if (disabled) {
    return (
      <div className="flex w-full items-start justify-between gap-3 rounded-2xl border border-border/40 p-3 text-left opacity-40 select-none">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          {icon}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-semibold text-muted-foreground">{label}</span>
              {badgeEl}
            </div>
            {description ? (
              <p className="mt-0.5 text-[0.714em] leading-snug text-muted-foreground/70">{description}</p>
            ) : null}
          </div>
        </div>
      </div>
    );
  }

  // Se non c'è un'icona esplicita o se showRadio è true, mostra il radio indicator
  const displayRadio = showRadio ?? !icon;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick?.();
        }
      }}
      className={cn(
        "flex w-full items-start justify-between gap-3 rounded-2xl p-3 text-left transition-all duration-150 cursor-pointer select-none",
        selected
          ? "border-2 border-zinc-900 dark:border-white bg-zinc-900/[0.05] dark:bg-white/[0.08] text-foreground shadow-xs"
          : "border border-border/70 dark:border-white/10 bg-background/50 dark:bg-zinc-900/30 text-muted-foreground opacity-75 hover:opacity-100 hover:border-border hover:bg-muted/30",
      )}
    >
      <div className="flex items-start gap-3 min-w-0 flex-1">
        {displayRadio ? (
          <div
            className={cn(
              "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full transition-all",
              selected
                ? "border-2 border-zinc-900 dark:border-white bg-background"
                : "border border-zinc-400 dark:border-zinc-600 bg-transparent",
            )}
          >
            {selected ? (
              <div className="h-2 w-2 rounded-full bg-zinc-900 dark:bg-white" />
            ) : null}
          </div>
        ) : (
          icon
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                "text-xs leading-snug",
                selected ? "font-bold text-foreground" : "font-medium text-muted-foreground",
              )}
            >
              {label}
            </span>
            {badgeEl}
          </div>
          {description ? (
            <p
              className={cn(
                "mt-0.5 text-[0.714em] leading-snug",
                selected
                  ? "text-foreground/85 dark:text-zinc-200 font-medium"
                  : "text-muted-foreground/75",
              )}
            >
              {description}
            </p>
          ) : null}
        </div>
      </div>
      <div className="mt-0.5 flex shrink-0 items-center gap-1">
        {trailing}
        {selected ? (
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 shadow-2xs">
            <Check size={11} strokeWidth={2.5} aria-hidden />
          </span>
        ) : null}
      </div>
    </div>
  );
}

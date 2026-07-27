"use client";

import { Check } from "lucide-react";

import { cn } from "@/lib/cn";

export function ComposerOptionRow({
  label,
  description,
  selected,
  disabled,
  badge,
  icon,
  trailing,
  onClick,
}: {
  label: string;
  description?: string;
  selected?: boolean;
  disabled?: boolean;
  badge?: string;
  icon?: React.ReactNode;
  trailing?: React.ReactNode;
  onClick?: () => void;
}) {
  if (disabled) {
    return (
      <div className="flex w-full items-start justify-between gap-2 rounded-lg px-2.5 py-2 text-left opacity-55">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            {icon}
            <span className="text-xs font-semibold text-muted-foreground">{label}</span>
            {badge ? (
              <span className="rounded border border-border/60 bg-muted/40 px-1.5 py-0.5 text-[0.643em] font-semibold text-muted-foreground">
                {badge}
              </span>
            ) : null}
          </div>
          {description ? (
            <p className="mt-0.5 pl-0 text-[0.714em] leading-snug text-muted-foreground/80">{description}</p>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-start justify-between gap-2 rounded-lg px-2.5 py-2 text-left transition-colors",
        selected
          ? "bg-primary/10 text-primary"
          : "text-foreground hover:bg-muted/55",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          {icon}
          <span className="text-xs font-semibold">{label}</span>
        </div>
        {description ? (
          <p
            className={cn(
              "mt-0.5 text-[0.714em] leading-snug",
              selected ? "text-primary/80" : "text-muted-foreground",
            )}
          >
            {description}
          </p>
        ) : null}
      </div>
      <div className="mt-0.5 flex shrink-0 items-center gap-1">
        {trailing}
        {selected ? <Check size={12} aria-hidden /> : null}
      </div>
    </button>
  );
}

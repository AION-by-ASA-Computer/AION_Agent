"use client";

import { Eye, Star } from "lucide-react";
import { cn } from "@/lib/cn";

export type PickerItem = {
  id: string;
  description: string;
  on: boolean;
  /** Blocks attaching; shown with a badge. */
  blockedLabel?: string;
  critical?: boolean;
};

function Switch({ on, disabled }: { on: boolean; disabled?: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "relative h-5 w-9 shrink-0 rounded-full transition-colors duration-200",
        on ? "bg-foreground" : "bg-muted-foreground/30",
        disabled && "opacity-50",
      )}
    >
      <span
        className={cn(
          "absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-background shadow-sm transition-transform duration-200 ease-out",
          on && "translate-x-4",
        )}
      />
    </span>
  );
}

/** One row per item: a single switch to attach it, an optional star to mark it critical. */
export function PickerList({
  items,
  onToggle,
  onCritical,
  criticalOn,
  criticalOff,
  onPreview,
  previewLabel,
}: {
  items: PickerItem[];
  onToggle: (id: string) => void;
  onCritical?: (id: string) => void;
  criticalOn?: string;
  criticalOff?: string;
  onPreview?: (id: string) => void;
  previewLabel?: string;
}) {
  return (
    <ul className="divide-y divide-border/50 overflow-hidden rounded-2xl border border-border/70 bg-card">
      {items.map((it) => (
        <li key={it.id} className="flex items-center">
          <button
            type="button"
            role="switch"
            aria-checked={it.on}
            onClick={() => onToggle(it.id)}
            className={cn(
              "focus-ring flex min-w-0 flex-1 items-center gap-3.5 px-4 py-3 text-left transition-colors hover:bg-secondary/50 focus-visible:bg-secondary/50",
              it.blockedLabel && !it.on && "cursor-not-allowed opacity-60",
            )}
          >
            <Switch on={it.on} disabled={!!it.blockedLabel && !it.on} />
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2">
                <span className="truncate font-mono text-[13px] font-medium">{it.id}</span>
                {it.blockedLabel && (
                  <span className="shrink-0 rounded-full bg-warning/15 px-2 py-0.5 text-[11px] font-medium text-warning">
                    {it.blockedLabel}
                  </span>
                )}
              </span>
              <span className="mt-0.5 block truncate text-xs text-muted-foreground" title={it.description}>
                {it.description}
              </span>
            </span>
          </button>
          {onCritical && it.on && (
            <button
              type="button"
              onClick={() => onCritical(it.id)}
              aria-pressed={!!it.critical}
              title={it.critical ? criticalOn : criticalOff}
              aria-label={it.critical ? criticalOn : criticalOff}
              className="focus-ring mr-1 last:mr-2 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              <Star className={cn("h-4 w-4", it.critical && "fill-warning text-warning")} aria-hidden />
            </button>
          )}
          {onPreview && (
            <button
              type="button"
              onClick={() => onPreview(it.id)}
              title={previewLabel}
              aria-label={`${previewLabel}: ${it.id}`}
              className="focus-ring mr-2 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              <Eye className="h-4 w-4" aria-hidden />
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

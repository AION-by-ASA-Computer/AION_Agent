"use client";

import type { LucideIcon } from "lucide-react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { ShimmerText } from "@/components/chat/ShimmerText";

type Props = {
  icon: LucideIcon;
  title: string;
  subtitle?: string;
  className?: string;
};

/** Compact status row for background work (compacting, generating, tool prep). */
export function StatusProgressCard({ icon: Icon, title, subtitle, className }: Props) {
  return (
    <div
      className={cn(
        "flex max-w-xl items-center gap-3 rounded-xl border border-border/60 bg-muted/25 px-3.5 py-3",
        className,
      )}
      role="status"
      aria-live="polite"
    >
      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-border/50 bg-background/80">
        <Icon className="size-4 text-primary/90" aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <ShimmerText className="text-sm font-medium leading-snug">{title}</ShimmerText>
        {subtitle ? (
          <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
        ) : null}
      </div>
      <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" aria-hidden />
    </div>
  );
}

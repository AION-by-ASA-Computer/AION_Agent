"use client";

import { Code2, Terminal, Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { ShimmerText } from "@/components/chat/ShimmerText";

type Props = {
  title?: string;
  isScript?: boolean;
  className?: string;
};

/**
 * Modern animated loader for code and script generation.
 * Replaces static modal/progress cards with an active, pulsing indicator
 * so the user clearly sees that the agent is actively writing code.
 */
export function CodeGenerationLoader({ title, isScript = true, className }: Props) {
  const displayTitle = title?.trim() || "";

  return (
    <div
      className={cn(
        "group relative flex max-w-xl items-center gap-3.5 rounded-2xl border border-primary/25 bg-card/85 dark:bg-card/90 p-3.5 shadow-2xs backdrop-blur-md transition-all duration-200 animate-in fade-in slide-in-from-top-1",
        className,
      )}
      role="status"
      aria-live="polite"
    >
      {/* Icon badge with pulsing accent */}
      <div className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-primary/30 bg-primary/10 text-primary dark:bg-primary/20 shadow-2xs">
        {isScript ? (
          <Terminal className="size-5 animate-pulse text-primary" aria-hidden="true" />
        ) : (
          <Code2 className="size-5 animate-pulse text-primary" aria-hidden="true" />
        )}
      </div>

      {/* Main label with shimmer and active typing bounce */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <ShimmerText className="text-sm font-semibold tracking-tight text-foreground">
            {displayTitle ? `Scrittura di ${displayTitle}…` : "Generazione codice in corso…"}
          </ShimmerText>
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
          <span>L&apos;agente sta componendo ed eseguendo il codice</span>
          <span className="inline-flex items-center gap-0.5" aria-hidden="true">
            <span className="size-1 rounded-full bg-primary/70 animate-bounce [animation-delay:-0.3s]" />
            <span className="size-1 rounded-full bg-primary/70 animate-bounce [animation-delay:-0.15s]" />
            <span className="size-1 rounded-full bg-primary/70 animate-bounce" />
          </span>
        </div>
      </div>

      {/* Spinner */}
      <div className="flex items-center shrink-0">
        <Loader2 className="size-4 animate-spin text-primary" aria-hidden="true" />
      </div>
    </div>
  );
}

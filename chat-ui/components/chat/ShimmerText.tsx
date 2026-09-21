"use client";

import { cn } from "@/lib/cn";

type Props = {
  children: React.ReactNode;
  className?: string;
  as?: "span" | "p" | "div";
};

import { useT } from "@/lib/i18n/use-t";

/** OpenWebUI-style animated label for in-progress background work. */
export function ShimmerText({ children, className, as: Tag = "span" }: Props) {
  return (
    <Tag className={cn("agent-shimmer-text", className)} role="status" aria-live="polite">
      {children}
    </Tag>
  );
}

/** Unified animated label for in-progress thinking/warmup across all chat views. */
export function AgentWorkingShimmer({ label, className }: { label?: string; className?: string }) {
  const t = useT();
  const text = label || t("chat.agent_status.thinking");
  return (
    <div className={cn("flex items-center py-1 select-none", className)}>
      <ShimmerText className="text-sm leading-relaxed">{text}</ShimmerText>
    </div>
  );
}

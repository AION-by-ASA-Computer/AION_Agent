"use client";

import { cn } from "@/lib/cn";

type Props = {
  children: React.ReactNode;
  className?: string;
  as?: "span" | "p" | "div";
};

/** OpenWebUI-style animated label for in-progress background work. */
export function ShimmerText({ children, className, as: Tag = "span" }: Props) {
  return (
    <Tag className={cn("agent-shimmer-text", className)} role="status" aria-live="polite">
      {children}
    </Tag>
  );
}

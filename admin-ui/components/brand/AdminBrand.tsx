"use client";

import { cn } from "@/lib/cn";
import { Logo } from "@/components/ui/logo";

export function AdminBrand({ className = "max-w-[140px]" }: { className?: string }) {
  return (
    <Logo
      width="190"
      className={cn("h-15 w-auto", className)}
    />
  );
}

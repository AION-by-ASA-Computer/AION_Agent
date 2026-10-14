"use client";

import { Search } from "lucide-react";
import { cn } from "@/lib/cn";
import { inputCls } from "./classes";

export function SearchField({
  value,
  onChange,
  placeholder,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  /** Background override; defaults to the card surface. */
  className?: string;
}) {
  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className={cn(inputCls, "pl-10", className ?? "bg-card")}
      />
    </div>
  );
}

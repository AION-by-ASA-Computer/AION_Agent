"use client";

import { Check } from "lucide-react";

import { cn } from "@/lib/cn";

export type ProfileOption = {
  slug: string;
  name: string;
  description?: string;
};

export function ProfileOptionGrid({
  profiles,
  value,
  onChange,
  emptyLabel,
}: {
  profiles: ProfileOption[];
  value: string;
  onChange: (slug: string) => void;
  emptyLabel?: string;
}) {
  if (!profiles.length) {
    return (
      <p className="text-xs italic text-muted-foreground">{emptyLabel || "No profiles"}</p>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {profiles.map((p) => {
        const selected = p.slug === value;
        return (
          <button
            key={p.slug}
            type="button"
            onClick={() => onChange(p.slug)}
            className={cn(
              "group relative rounded-2xl border px-3.5 py-3 text-left transition hover:shadow-sm",
              selected
                ? "border-primary/40 bg-primary/8 shadow-[0_0_24px_-12px_hsl(var(--primary)/0.5)]"
                : "border-border/70 bg-card/30 hover:border-primary/25 hover:bg-card/50",
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="text-sm font-semibold text-foreground">{p.name}</div>
                {p.description ? (
                  <p className="mt-1 line-clamp-2 text-[0.786em] leading-snug text-muted-foreground">
                    {p.description}
                  </p>
                ) : null}
              </div>
              {selected ? (
                <Check size={14} className="mt-0.5 shrink-0 text-primary" aria-hidden />
              ) : null}
            </div>
          </button>
        );
      })}
    </div>
  );
}

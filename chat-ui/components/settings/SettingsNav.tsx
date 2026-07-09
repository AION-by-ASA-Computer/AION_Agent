"use client";

import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/cn";

export type SettingsTab = "profile" | "appearance" | "security" | "instructions";

export function SettingsNav({
  activeTab,
  onChange,
  items,
}: {
  activeTab: SettingsTab;
  onChange: (tab: SettingsTab) => void;
  items: Array<{ id: SettingsTab; label: string; icon: LucideIcon }>;
}) {
  return (
    <nav className="flex flex-row gap-1 overflow-x-auto border-b border-border/50 pb-3 md:flex-col md:overflow-visible md:border-b-0 md:border-r md:pb-0 md:pr-5">
      {items.map((item) => {
        const Icon = item.icon;
        const active = activeTab === item.id;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onChange(item.id)}
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-xs font-semibold whitespace-nowrap transition md:w-full",
              active
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4 shrink-0" aria-hidden />
            <span>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}

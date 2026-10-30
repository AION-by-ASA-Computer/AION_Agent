"use client";

import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/cn";

export type SettingsTab =
  | "profile"
  | "appearance"
  | "security"
  | "api-keys"
  | "whatsapp"
  | "instructions"
  | "tunings";

/** Section list: a sticky column on wide screens, a scrolling strip on narrow ones. */
export function SettingsNav({
  activeTab,
  onChange,
  items,
  label,
}: {
  activeTab: SettingsTab;
  onChange: (tab: SettingsTab) => void;
  items: Array<{ id: SettingsTab; label: string; icon: LucideIcon }>;
  label?: string;
}) {
  return (
    <nav aria-label={label} className="-mx-4 overflow-x-auto px-4 sm:-mx-6 sm:px-6 lg:mx-0 lg:overflow-visible lg:px-0">
      <ul className="flex gap-1 lg:sticky lg:top-6 lg:flex-col">
        {items.map(({ id, label: itemLabel, icon: Icon }) => {
          const active = activeTab === id;
          return (
            <li key={id} className="shrink-0">
              <button
                type="button"
                onClick={() => onChange(id)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "focus-ring flex w-full items-center gap-2.5 whitespace-nowrap rounded-xl px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-secondary font-medium text-foreground"
                    : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden />
                {itemLabel}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

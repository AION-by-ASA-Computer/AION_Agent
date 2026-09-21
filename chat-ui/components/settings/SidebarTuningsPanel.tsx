"use client";

import { Bookmark, SlidersHorizontal } from "lucide-react";

import { RuntimePresetsPanel } from "@/components/settings/RuntimePresetsPanel";
import { RuntimeSettingsForm } from "@/components/settings/RuntimeSettingsForm";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import type { SidebarTuningsTab } from "@/lib/shell/shell-context";

export function SidebarTuningsPanel({
  tab,
  onTabChange,
}: {
  tab: SidebarTuningsTab;
  onTabChange: (tab: SidebarTuningsTab) => void;
}) {
  const t = useT();
  const items: Array<{ id: SidebarTuningsTab; label: string; icon: typeof SlidersHorizontal }> = [
    { id: "runtime", label: t("settings.tab.runtime"), icon: SlidersHorizontal },
    { id: "presets", label: t("settings.tab.presets"), icon: Bookmark },
  ];

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden px-2">
      <p className="mb-3 shrink-0 px-1 text-[0.65rem] font-semibold uppercase tracking-wider text-muted-foreground">
        {t("sidebar.tunings_section")}
      </p>
      <nav
        className="mb-3 flex shrink-0 gap-1.5 rounded-lg border border-border/40 bg-muted/30 p-1"
        aria-label={t("sidebar.tunings_section")}
      >
        {items.map((item) => {
          const Icon = item.icon;
          const active = tab === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onTabChange(item.id)}
              title={item.label}
              className={cn(
                "flex min-w-0 flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-2 text-[0.7rem] font-medium transition",
                active
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-background/60 hover:text-foreground",
              )}
            >
              <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
              <span className="truncate">{item.label}</span>
            </button>
          );
        })}
      </nav>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-4 [-webkit-overflow-scrolling:touch]">
        {tab === "runtime" ? <RuntimeSettingsForm /> : null}
        {tab === "presets" ? <RuntimePresetsPanel /> : null}
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { Bookmark, SlidersHorizontal } from "lucide-react";

import { RuntimePresetsPanel } from "@/components/settings/RuntimePresetsPanel";
import { RuntimeSettingsForm } from "@/components/settings/RuntimeSettingsForm";
import { SettingsCard } from "@/components/settings/SettingsCard";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n/use-t";
import type { SidebarTuningsTab } from "@/lib/shell/shell-context";

export function TuningsSettingsSection({
  initialTab = "runtime",
}: {
  initialTab?: SidebarTuningsTab;
}) {
  const t = useT();
  const [subTab, setSubTab] = useState<SidebarTuningsTab>(initialTab);

  return (
    <SettingsCard
      title={t("settings.tunings.title") || t("sidebar.tunings")}
      description={t("settings.tunings.desc") || t("settings.runtime.hint")}
      icon={<SlidersHorizontal className="h-4.5 w-4.5" aria-hidden />}
    >
      <div className="space-y-5">
        {/* Sub-tab switcher */}
        <div className="flex items-center gap-2 border-b border-border/40 pb-3">
          <button
            type="button"
            onClick={() => setSubTab("runtime")}
            className={cn(
              "flex items-center gap-2 rounded-xl px-3.5 py-2 text-xs font-semibold transition cursor-pointer",
              subTab === "runtime"
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
            )}
          >
            <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
            <span>{t("settings.tab.runtime")}</span>
          </button>

          <button
            type="button"
            onClick={() => setSubTab("presets")}
            className={cn(
              "flex items-center gap-2 rounded-xl px-3.5 py-2 text-xs font-semibold transition cursor-pointer",
              subTab === "presets"
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
            )}
          >
            <Bookmark className="h-3.5 w-3.5" aria-hidden />
            <span>{t("settings.tab.presets")}</span>
          </button>
        </div>

        <div>
          {subTab === "runtime" ? <RuntimeSettingsForm /> : <RuntimePresetsPanel />}
        </div>
      </div>
    </SettingsCard>
  );
}

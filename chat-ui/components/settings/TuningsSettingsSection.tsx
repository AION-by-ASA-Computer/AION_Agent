"use client";

import { RuntimePresetMenu } from "@/components/settings/RuntimePresetMenu";
import { RuntimeSettingsForm } from "@/components/settings/RuntimeSettingsForm";
import { useT } from "@/lib/i18n/use-t";
import type { SidebarTuningsTab } from "@/lib/shell/shell-context";
import { SectionHead } from "./ui";

export function TuningsSettingsSection({
  initialTab = "runtime",
}: {
  /** `presets` (legacy deep link) opens the preset menu on arrival. */
  initialTab?: SidebarTuningsTab;
}) {
  const t = useT();

  return (
    <>
      <SectionHead
        title={t("settings.tunings.title")}
        description={t("settings.tunings.desc")}
        action={<RuntimePresetMenu defaultOpen={initialTab === "presets"} />}
      />
      <RuntimeSettingsForm />
    </>
  );
}

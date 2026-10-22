"use client";

import { useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";

import { getLocale, setLocale, subscribe, type Locale } from "@/lib/i18n/i18n-store";
import { LOCALE_OPTIONS } from "@/lib/i18n/locale-options";
import { syncLanguagePreferenceToServer } from "@/lib/i18n/sync-language";
import { useT } from "@/lib/i18n/use-t";
import { useChatTheme } from "@/lib/theme/chat-theme";
import { useChatFontSize } from "@/lib/theme/chat-font-scale";
import { useStoredToken } from "@/lib/auth/use-stored-auth";
import { FontSizeSlider } from "./FontSizeSlider";
import { Select } from "./Select";
import { Group, Row, RowList, SectionHead, Segmented } from "./ui";

/** Theme, text size and language. Every change applies (and persists) immediately. */
export function AppearanceSection({
  onLanguageSaved,
}: {
  onLanguageSaved?: (message: string) => void;
}) {
  const t = useT();
  const token = useStoredToken();
  const [theme, setTheme] = useChatTheme();
  const [fontSize, setFontSize] = useChatFontSize();
  const locale = useSyncExternalStore(subscribe, getLocale, () => "en" as Locale);

  async function handleLanguageChange(code: Locale) {
    setLocale(code);
    if (token) {
      const ok = await syncLanguagePreferenceToServer(token, code);
      onLanguageSaved?.(ok ? t("toast.language_saved") : t("toast.language_server_error"));
    } else {
      onLanguageSaved?.(t("toast.language_local"));
    }
  }

  return (
    <>
      <SectionHead title={t("settings.appearance.title")} description={t("settings.appearance.desc")} />
      <Group>
        <RowList>
          <Row label={t("settings.appearance.theme_label")} description={t("settings.appearance.theme_desc")}>
            <Segmented
              label={t("settings.appearance.theme_label")}
              value={theme === "light" ? "light" : "dark"}
              onChange={setTheme}
              className="w-full sm:w-auto"
              options={[
                { value: "light", label: t("sidebar.profile_menu.theme_light"), icon: <Sun className="h-3.5 w-3.5" aria-hidden /> },
                { value: "dark", label: t("sidebar.profile_menu.theme_dark"), icon: <Moon className="h-3.5 w-3.5" aria-hidden /> },
              ]}
            />
          </Row>
          <Row label={t("settings.appearance.font_scale_label")} description={t("settings.appearance.font_scale_desc")}>
            <div className="flex items-center gap-4 sm:w-80">
              <FontSizeSlider
                value={fontSize}
                onChange={setFontSize}
                aria-label={t("settings.appearance.font_scale_label")}
                className="max-w-none flex-1"
              />
              <output className="w-11 shrink-0 text-right font-mono text-xs tabular-nums text-muted-foreground">
                {fontSize}px
              </output>
            </div>
          </Row>
          <Row label={t("settings.appearance.language_label")} description={t("settings.section.language.desc")}>
            <div className="sm:w-56">
              <Select
                aria-label={t("settings.appearance.language_label")}
                value={locale}
                onChange={(code) => void handleLanguageChange(code)}
                options={LOCALE_OPTIONS.map((l) => ({ value: l.code, label: l.name }))}
              />
            </div>
          </Row>
        </RowList>
      </Group>
    </>
  );
}

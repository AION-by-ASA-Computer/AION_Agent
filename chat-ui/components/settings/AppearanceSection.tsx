"use client";

import { Check, ChevronDown, Moon, Sun } from "lucide-react";

import { cn } from "@/lib/cn";
import { getLocale, setLocale, subscribe, type Locale } from "@/lib/i18n/i18n-store";
import { LOCALE_OPTIONS } from "@/lib/i18n/locale-options";
import { syncLanguagePreferenceToServer } from "@/lib/i18n/sync-language";
import { useT } from "@/lib/i18n/use-t";
import { useChatTheme } from "@/lib/theme/chat-theme";
import {
  CHAT_FONT_SCALE_PX,
  useChatFontScale,
  type ChatFontScale,
} from "@/lib/theme/chat-font-scale";
import { useStoredToken } from "@/lib/auth/use-stored-auth";
import { useSyncExternalStore, useState } from "react";
import { SettingsFieldRow } from "./SettingsCard";

export function AppearanceSection({
  onLanguageSaved,
}: {
  onLanguageSaved?: (message: string) => void;
}) {
  const t = useT();
  const token = useStoredToken();
  const [theme, setTheme] = useChatTheme();
  const [fontScale, setFontScale] = useChatFontScale();
  const locale = useSyncExternalStore(subscribe, getLocale, () => "en" as Locale);
  const [langOpen, setLangOpen] = useState(false);

  async function handleLanguageChange(code: Locale) {
    setLocale(code);
    setLangOpen(false);
    if (token) {
      const ok = await syncLanguagePreferenceToServer(token, code);
      onLanguageSaved?.(
        ok ? t("toast.language_saved") : t("toast.language_server_error"),
      );
    } else {
      onLanguageSaved?.(t("toast.language_local"));
    }
  }

  const current = LOCALE_OPTIONS.find((l) => l.code === locale) ?? LOCALE_OPTIONS[0];

  const fontScaleOptions: ChatFontScale[] = ["small", "medium", "large"];

  return (
    <div className="space-y-1">
      <SettingsFieldRow
        label={t("settings.appearance.font_scale_label")}
        hint={t("settings.appearance.font_scale_desc")}
      >
        <div className="grid max-w-xs grid-cols-3 gap-1 rounded-xl bg-muted/40 p-1">
          {fontScaleOptions.map((scale) => (
            <button
              key={scale}
              type="button"
              onClick={() => setFontScale(scale)}
              className={cn(
                "focus-ring rounded-lg px-2 py-2 text-xs font-semibold transition",
                fontScale === scale
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t(`settings.appearance.font_scale_${scale}`)}
              <span className="mt-0.5 block text-[10px] font-normal text-muted-foreground">
                {CHAT_FONT_SCALE_PX[scale]}px
              </span>
            </button>
          ))}
        </div>
      </SettingsFieldRow>

      <SettingsFieldRow
        label={t("settings.appearance.theme_label")}
        hint={t("settings.appearance.theme_desc")}
      >
        <div className="grid max-w-xs grid-cols-2 gap-1 rounded-xl bg-muted/40 p-1">
          <button
            type="button"
            onClick={() => setTheme("light")}
            className={cn(
              "focus-ring flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition",
              theme === "light"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Sun className="h-3.5 w-3.5" aria-hidden />
            {t("sidebar.profile_menu.theme_light")}
          </button>
          <button
            type="button"
            onClick={() => setTheme("dark")}
            className={cn(
              "focus-ring flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition",
              theme === "dark"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Moon className="h-3.5 w-3.5" aria-hidden />
            {t("sidebar.profile_menu.theme_dark")}
          </button>
        </div>
      </SettingsFieldRow>

      <SettingsFieldRow
        label={t("settings.appearance.language_label")}
        hint={t("settings.section.language.desc")}
      >
        <div className="relative max-w-xs">
          <button
            type="button"
            onClick={() => setLangOpen((prev) => !prev)}
            className="focus-ring flex w-full items-center justify-between gap-2 rounded-xl border border-border/50 bg-background/50 px-3.5 py-2.5 text-sm transition hover:bg-muted/40"
          >
            <span className="flex items-center gap-2 text-xs font-semibold">
              <span aria-hidden>{current.flag}</span>
              {current.name}
            </span>
            <ChevronDown
              className={cn("h-4 w-4 text-muted-foreground transition", langOpen && "rotate-180")}
              aria-hidden
            />
          </button>
          {langOpen ? (
            <>
              <button
                type="button"
                className="fixed inset-0 z-40"
                aria-label={t("btn.cancel")}
                onClick={() => setLangOpen(false)}
              />
              <div className="absolute left-0 right-0 z-50 mt-1.5 rounded-xl border border-border/60 bg-card/95 p-1 shadow-xl backdrop-blur-xl">
                {LOCALE_OPTIONS.map((lang) => (
                  <button
                    key={lang.code}
                    type="button"
                    onClick={() => void handleLanguageChange(lang.code)}
                    className={cn(
                      "focus-ring flex w-full items-center justify-between rounded-lg px-3 py-2 text-xs font-semibold transition",
                      locale === lang.code
                        ? "bg-primary/10 text-primary"
                        : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                    )}
                  >
                    <span className="flex items-center gap-2">
                      <span aria-hidden>{lang.flag}</span>
                      {lang.name}
                    </span>
                    {locale === lang.code ? <Check className="h-3.5 w-3.5" aria-hidden /> : null}
                  </button>
                ))}
              </div>
            </>
          ) : null}
        </div>
      </SettingsFieldRow>
    </div>
  );
}
